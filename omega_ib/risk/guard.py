"""The single choke point for order placement (CLAUDE.md rule 2).

Nothing else in this codebase may call `broker.place_order` -- enforced by the
grep-based test `tests/test_guard_enforcement.py`. Every hard limit in CLAUDE.md
rule 4 is checked here before an order reaches the broker, and every rejection
(and every placed order) is written to the audit log with a reason (rule 7).

The AI layer (ai/reviewer.py) is advisory only: it may propose orders, veto them
before they reach here, or ask a caller to tighten a limit -- it can never call
this module in a way that loosens a check below, and it never touches the
broker directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from omega_ib.broker.base import BrokerBase, OrderRequest, OrderStatus
from omega_ib.config import Settings
from omega_ib.config import settings as default_settings
from omega_ib.store.db import write_audit


class GuardRejection(Exception):
    """Raised when the guard blocks an order. The message is the reason logged to audit."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


@dataclass
class GuardContext:
    """Portfolio state snapshot the guard needs to evaluate one proposed order.

    Callers (execution/engine.py, strategies) are responsible for computing this
    from live broker/portfolio state before calling RiskGuard.place_order.
    """

    nav: float
    day_realized_pnl: float = 0.0
    day_unrealized_pnl: float = 0.0
    open_positions: int = 0
    is_new_position: bool = False
    current_position_notional: float = 0.0
    underlying_shares_held: float = 0.0
    estimated_price: float | None = None
    is_day_trade: bool = False
    day_trades_count: int = 0


def fixed_fractional_size(
    nav: float,
    risk_pct: float,
    entry_price: float,
    stop_price: float,
    contract_multiplier: float = 1.0,
    settings: Settings | None = None,
) -> int:
    """Size a position so a stop-out risks exactly `risk_pct` of NAV.

    The result is additionally capped by max_order_notional and max_position_pct_nav
    so a sizing bug can never itself become a limit breach -- config only tightens.
    """
    s = settings or default_settings
    risk_per_unit = abs(entry_price - stop_price) * contract_multiplier
    if risk_per_unit <= 0 or entry_price <= 0:
        return 0
    risk_amount = nav * risk_pct
    qty = int(risk_amount // risk_per_unit)
    max_qty_by_notional = int(s.max_order_notional // (entry_price * contract_multiplier))
    max_qty_by_position_pct = int((nav * s.max_position_pct_nav) // (entry_price * contract_multiplier))
    return max(0, min(qty, max_qty_by_notional, max_qty_by_position_pct))


def atr_stop_price(entry_price: float, atr: float, atr_multiplier: float = 2.0, direction: str = "long") -> float:
    """Stop price placed `atr_multiplier` ATRs away from entry, in the losing direction."""
    if direction == "long":
        return entry_price - atr_multiplier * atr
    return entry_price + atr_multiplier * atr


def size_by_fixed_fractional_atr(
    nav: float,
    risk_pct: float,
    entry_price: float,
    atr: float,
    atr_multiplier: float = 2.0,
    direction: str = "long",
    contract_multiplier: float = 1.0,
    settings: Settings | None = None,
) -> int:
    stop = atr_stop_price(entry_price, atr, atr_multiplier, direction)
    return fixed_fractional_size(nav, risk_pct, entry_price, stop, contract_multiplier, settings)


class RiskGuard:
    """Pre-trade checks, kill switch, and the only sanctioned path to broker.place_order."""

    def __init__(self, broker: BrokerBase, settings: Settings | None = None) -> None:
        self.broker = broker
        self.settings = settings or default_settings
        self._kill_switch_engaged_manually = False

    # --- kill switch (CLAUDE.md rule 3) ---

    @property
    def kill_switch_active(self) -> bool:
        return self.settings.kill_switch_active or self._kill_switch_engaged_manually

    def engage_kill_switch(self, reason: str) -> None:
        """Cancel all open orders and block new ones until reset_kill_switch() is called."""
        self._kill_switch_engaged_manually = True
        Path(self.settings.kill_switch_file).touch()
        self.broker.cancel_all()
        write_audit("kill_switch_engaged", reason)

    def reset_kill_switch(self) -> None:
        self._kill_switch_engaged_manually = False
        kill_file = Path(self.settings.kill_switch_file)
        if kill_file.exists():
            kill_file.unlink()
        write_audit("kill_switch_reset", "manually reset")

    # --- the checks (CLAUDE.md rule 4) ---

    def check_order(self, order: OrderRequest, ctx: GuardContext) -> None:
        """Raise GuardRejection if the order must be blocked; otherwise return None."""
        checks = (
            self._check_kill_switch,
            self._check_trading_mode,
            self._check_market_order_on_options,
            self._check_naked_short_call,
            self._check_max_options_contracts,
            self._check_max_order_notional,
            self._check_max_position_pct_nav,
            self._check_max_open_positions,
            self._check_max_daily_loss,
            self._check_pdt,
        )
        for check in checks:
            reason = check(order, ctx)
            if reason:
                write_audit(
                    "guard_rejection",
                    reason,
                    {"symbol": order.contract.symbol, "action": order.action, "quantity": order.quantity},
                )
                raise GuardRejection(reason)

    def place_order(self, order: OrderRequest, ctx: GuardContext) -> OrderStatus:
        """The only sanctioned path to broker.place_order. Raises GuardRejection if blocked."""
        self.check_order(order, ctx)
        status = self.broker.place_order(order)
        write_audit(
            "order_placed",
            f"{order.action} {order.quantity} {order.contract.symbol} ({order.order_type})",
            {"symbol": order.contract.symbol, "order_id": status.order_id},
        )
        return status

    # --- individual checks: each returns None (ok) or a rejection reason string ---

    def _check_kill_switch(self, order: OrderRequest, ctx: GuardContext) -> str | None:
        if self.kill_switch_active:
            return "kill switch is active: new orders are blocked until manually reset"
        return None

    def _check_trading_mode(self, order: OrderRequest, ctx: GuardContext) -> str | None:
        if self.settings.is_read_only:
            return (
                "system is read-only: TRADING_MODE=live requires LIVE_CONFIRM="
                "I_ACCEPT_REAL_MONEY_RISK to execute"
            )
        return None

    def _check_market_order_on_options(self, order: OrderRequest, ctx: GuardContext) -> str | None:
        if order.contract.sec_type in ("OPT", "BAG") and order.order_type == "MKT":
            return "market orders on options are never permitted"
        return None

    def _check_naked_short_call(self, order: OrderRequest, ctx: GuardContext) -> str | None:
        if self._short_call_is_covered(order, ctx):
            return None
        return "naked short calls are never permitted"

    def _short_call_is_covered(self, order: OrderRequest, ctx: GuardContext) -> bool:
        c = order.contract
        if c.sec_type == "OPT":
            if not (order.action == "SELL" and c.right == "C"):
                return True
            shares_needed = order.quantity * 100
            return ctx.underlying_shares_held >= shares_needed
        if c.sec_type == "BAG":
            sell_calls = sum(leg.leg_ratio for leg in c.legs if leg.leg_action == "SELL" and leg.right == "C")
            buy_calls = sum(leg.leg_ratio for leg in c.legs if leg.leg_action == "BUY" and leg.right == "C")
            return sell_calls <= buy_calls
        return True

    def _order_notional(self, order: OrderRequest, ctx: GuardContext) -> float | None:
        price = order.limit_price or order.stop_price or ctx.estimated_price
        if price is None:
            return None
        multiplier = 100 if order.contract.sec_type in ("OPT", "BAG") else 1
        return price * order.quantity * multiplier

    def _check_max_options_contracts(self, order: OrderRequest, ctx: GuardContext) -> str | None:
        if order.contract.sec_type in ("OPT", "BAG") and order.quantity > self.settings.max_options_contracts_per_order:
            return (
                f"{order.quantity} contracts exceeds max_options_contracts_per_order "
                f"({self.settings.max_options_contracts_per_order})"
            )
        return None

    def _check_max_order_notional(self, order: OrderRequest, ctx: GuardContext) -> str | None:
        notional = self._order_notional(order, ctx)
        if notional is not None and notional > self.settings.max_order_notional:
            return f"order notional {notional:.2f} exceeds max_order_notional {self.settings.max_order_notional:.2f}"
        return None

    def _check_max_position_pct_nav(self, order: OrderRequest, ctx: GuardContext) -> str | None:
        notional = self._order_notional(order, ctx)
        if notional is None or ctx.nav <= 0:
            return None
        if order.action == "BUY":
            resulting = ctx.current_position_notional + notional
        else:
            resulting = max(0.0, ctx.current_position_notional - notional)
        pct = resulting / ctx.nav
        if pct > self.settings.max_position_pct_nav:
            return f"resulting position {pct:.1%} of NAV exceeds max_position_pct_nav {self.settings.max_position_pct_nav:.1%}"
        return None

    def _check_max_open_positions(self, order: OrderRequest, ctx: GuardContext) -> str | None:
        if ctx.is_new_position and ctx.open_positions >= self.settings.max_open_positions:
            return f"open positions ({ctx.open_positions}) at max_open_positions ({self.settings.max_open_positions})"
        return None

    def _check_max_daily_loss(self, order: OrderRequest, ctx: GuardContext) -> str | None:
        if ctx.nav <= 0:
            return None
        day_pnl_pct = (ctx.day_realized_pnl + ctx.day_unrealized_pnl) / ctx.nav
        if day_pnl_pct <= -self.settings.max_daily_loss_pct_nav:
            return (
                f"daily loss {day_pnl_pct:.2%} breaches max_daily_loss_pct_nav "
                f"{self.settings.max_daily_loss_pct_nav:.2%}"
            )
        return None

    def _check_pdt(self, order: OrderRequest, ctx: GuardContext) -> str | None:
        if ctx.nav < 25_000 and ctx.is_day_trade and ctx.day_trades_count >= 3:
            return "PDT rule: a 4th day trade in 5 business days is blocked for accounts under $25k NAV"
        return None

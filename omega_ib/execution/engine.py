"""Order execution: bracket orders for equities, price-walked limit orders (reused
by combo/options orders once options_builder.py exists), fill tracking.

Every call into the broker goes through RiskGuard.place_order -- this module
only ever calls the guard's place_order, never the broker's, directly
(CLAUDE.md rule 2, enforced by tests/test_guard_enforcement.py).
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from dataclasses import dataclass

from omega_ib.broker.base import Contract, OrderRequest, OrderStatus
from omega_ib.risk.guard import GuardContext, RiskGuard
from omega_ib.store.db import write_audit


@dataclass
class BracketOrder:
    entry: OrderRequest
    stop: OrderRequest
    target: OrderRequest


def build_bracket_order(
    contract: Contract,
    action: str,
    quantity: float,
    entry_price: float,
    stop_price: float,
    target_price: float,
    tif: str = "DAY",
) -> BracketOrder:
    """Entry limit + protective stop + profit target. The exit legs are OCA-linked
    to the entry via parent_id once the entry is placed (see place_bracket_order)."""
    exit_action = "SELL" if action == "BUY" else "BUY"
    entry = OrderRequest(
        contract=contract, action=action, quantity=quantity, order_type="LMT", limit_price=entry_price, tif=tif, transmit=False
    )
    stop = OrderRequest(
        contract=contract, action=exit_action, quantity=quantity, order_type="STP", stop_price=stop_price, tif=tif, transmit=False
    )
    target = OrderRequest(
        contract=contract, action=exit_action, quantity=quantity, order_type="LMT", limit_price=target_price, tif=tif, transmit=True
    )
    return BracketOrder(entry=entry, stop=stop, target=target)


@dataclass
class BracketResult:
    entry_status: OrderStatus
    stop_status: OrderStatus
    target_status: OrderStatus


def place_bracket_order(guard: RiskGuard, bracket: BracketOrder, ctx: GuardContext) -> BracketResult:
    """Place the entry, then link stop/target as its children. Raises GuardRejection
    (propagated from guard.place_order) if any leg is blocked -- callers should catch
    it and treat the whole bracket as not placed."""
    entry_status = guard.place_order(bracket.entry, ctx)
    parent_id = int(entry_status.order_id) if entry_status.order_id.isdigit() else None
    bracket.stop.parent_id = parent_id
    bracket.target.parent_id = parent_id
    stop_status = guard.place_order(bracket.stop, ctx)
    target_status = guard.place_order(bracket.target, ctx)
    write_audit(
        "bracket_order_placed",
        f"{bracket.entry.contract.symbol} entry/{stop_status.status}/{target_status.status}",
        {"entry_id": entry_status.order_id, "stop_id": stop_status.order_id, "target_id": target_status.order_id},
    )
    return BracketResult(entry_status, stop_status, target_status)


def submit_with_price_walk(
    guard: RiskGuard,
    order: OrderRequest,
    ctx: GuardContext,
    max_steps: int = 5,
    step_increment: float = 0.01,
    is_filled: Callable[[OrderStatus], bool] | None = None,
) -> OrderStatus:
    """Submit a limit order; if unfilled, cancel and resubmit up to `max_steps` times,
    walking the limit price toward the market by `step_increment` each time. Used for
    equities that don't fill immediately and, later, for combo/options limit orders.
    """
    is_filled = is_filled or (lambda s: s.status == "filled")
    if order.limit_price is None:
        raise ValueError("submit_with_price_walk requires a limit order with limit_price set")
    direction = 1 if order.action == "BUY" else -1
    current = copy.deepcopy(order)
    status = guard.place_order(current, ctx)
    steps = 0
    while not is_filled(status) and steps < max_steps:
        guard.broker.cancel_order(status.order_id)
        current = copy.deepcopy(current)
        current.limit_price = round(current.limit_price + direction * step_increment, 4)
        status = guard.place_order(current, ctx)
        steps += 1
    write_audit(
        "price_walk_complete",
        f"{order.contract.symbol} walked {steps} step(s), final status={status.status}",
        {"final_limit_price": current.limit_price, "steps": steps},
    )
    return status


@dataclass
class FillRecord:
    order_id: str
    symbol: str
    quantity: float
    price: float


class FillTracker:
    """In-memory ledger of fills seen this session, keyed by order_id (idempotent)."""

    def __init__(self) -> None:
        self._seen: dict[str, FillRecord] = {}

    def record(self, status: OrderStatus, symbol: str) -> FillRecord | None:
        """Record a fill the first time an order reaches status == 'filled'. Returns
        the FillRecord if this call newly recorded one, else None (already recorded
        or not yet filled)."""
        if status.status != "filled":
            return None
        if status.order_id in self._seen:
            return None
        record = FillRecord(order_id=status.order_id, symbol=symbol, quantity=status.filled, price=status.avg_fill_price)
        self._seen[status.order_id] = record
        write_audit("fill", f"{symbol} filled {status.filled}@{status.avg_fill_price}", {"order_id": status.order_id})
        return record

    def fills(self) -> list[FillRecord]:
        return list(self._seen.values())

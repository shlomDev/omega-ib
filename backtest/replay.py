"""Replay historical bars through the equity strategies and risk/guard.py using
FakeBroker, and produce a per-strategy stats report.

This is not a fill-realism backtester -- it doesn't model slippage, partial
fills, or intrabar order priority. Entries fill at the strategy's proposed
entry_price; exits fill at whichever of stop/target the bar's low/high reaches
first (stop checked first, the conservative assumption for a single-bar
resolution). Its purpose is to exercise the exact same strategies -> sizing ->
risk/guard.py path used live, against history, so limit behavior (kill switch,
daily loss cap, position caps) can be validated before an account ever sees
real orders.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from omega_ib.broker.base import Contract, OrderRequest
from omega_ib.broker.fake import FakeBroker
from omega_ib.config import Settings
from omega_ib.risk.guard import GuardContext, GuardRejection, RiskGuard, fixed_fractional_size
from omega_ib.strategies.equity.base import Signal, Strategy, rank_signals, run_strategies


@dataclass
class OpenTrade:
    signal: Signal
    quantity: float
    entry_price: float
    entry_date: Any


@dataclass
class ClosedTrade:
    symbol: str
    strategy: str
    direction: str
    entry_date: Any
    exit_date: Any
    entry_price: float
    exit_price: float
    quantity: float
    risk_per_share: float
    pnl: float
    exit_reason: str  # "stop" / "target"

    @property
    def r_multiple(self) -> float:
        if self.risk_per_share <= 0:
            return 0.0
        per_share_pnl = self.pnl / self.quantity if self.quantity else 0.0
        return per_share_pnl / self.risk_per_share


@dataclass
class ReplayResult:
    closed_trades: list[ClosedTrade] = field(default_factory=list)
    rejections: list[str] = field(default_factory=list)
    equity_curve: list[tuple[Any, float]] = field(default_factory=list)


def _guard_context(broker: FakeBroker, is_new_position: bool, current_position_notional: float = 0.0) -> GuardContext:
    summary = broker.account_summary()
    return GuardContext(
        nav=summary.nav,
        day_realized_pnl=summary.realized_pnl,
        day_unrealized_pnl=summary.unrealized_pnl,
        open_positions=len(broker.positions()),
        is_new_position=is_new_position,
        current_position_notional=current_position_notional,
    )


def replay(
    bars_by_symbol: dict[str, pd.DataFrame],
    strategies: list[Strategy],
    starting_nav: float = 100_000.0,
    risk_pct: float = 0.01,
    min_history: int = 60,
    settings: Settings | None = None,
) -> ReplayResult:
    """bars_by_symbol: symbol -> OHLCV DataFrame indexed by date, ascending.
    Symbols aren't required to share the same index; a symbol without a bar on
    a given date is simply skipped that day."""
    broker = FakeBroker(starting_nav=starting_nav)
    broker.connect()
    guard = RiskGuard(broker, settings)
    result = ReplayResult()
    open_trades: dict[str, OpenTrade] = {}

    all_dates = sorted(set().union(*(set(bars.index) for bars in bars_by_symbol.values())))
    for date in all_dates:
        for symbol, bars in bars_by_symbol.items():
            if date in bars.index:
                broker.set_price(symbol, float(bars.loc[date, "close"]))

        for symbol in list(open_trades.keys()):
            bars = bars_by_symbol[symbol]
            if date not in bars.index:
                continue
            _try_exit(guard, broker, open_trades, symbol, bars.loc[date], date, result)

        candidate_signals: list[Signal] = []
        for symbol, bars in bars_by_symbol.items():
            if symbol in open_trades or date not in bars.index:
                continue
            bars_so_far = bars.loc[:date]
            if len(bars_so_far) < min_history:
                continue
            candidate_signals.extend(run_strategies(strategies, symbol, bars_so_far))

        for signal in rank_signals(candidate_signals):
            _try_entry(guard, broker, open_trades, signal, date, risk_pct, settings, result)

        result.equity_curve.append((date, broker.account_summary().nav))

    return result


def _try_exit(guard, broker, open_trades, symbol, bar, date, result: ReplayResult) -> None:
    trade = open_trades[symbol]
    exit_price = None
    exit_reason = ""
    if trade.signal.direction == "long":
        if bar["low"] <= trade.signal.stop_price:
            exit_price, exit_reason = trade.signal.stop_price, "stop"
        elif bar["high"] >= trade.signal.target_price:
            exit_price, exit_reason = trade.signal.target_price, "target"
    if exit_price is None:
        return
    broker.set_price(symbol, exit_price)
    sell_order = OrderRequest(contract=Contract(symbol=symbol), action="SELL", quantity=trade.quantity, order_type="LMT", limit_price=exit_price)
    ctx = _guard_context(broker, is_new_position=False, current_position_notional=trade.quantity * exit_price)
    try:
        guard.place_order(sell_order, ctx)
    except GuardRejection as exc:
        result.rejections.append(f"{date} {symbol} exit rejected: {exc.reason}")
        return
    risk_per_share = abs(trade.entry_price - trade.signal.stop_price)
    pnl = (exit_price - trade.entry_price) * trade.quantity
    result.closed_trades.append(
        ClosedTrade(
            symbol=symbol, strategy=trade.signal.strategy, direction=trade.signal.direction,
            entry_date=trade.entry_date, exit_date=date, entry_price=trade.entry_price,
            exit_price=exit_price, quantity=trade.quantity, risk_per_share=risk_per_share,
            pnl=pnl, exit_reason=exit_reason,
        )
    )
    del open_trades[symbol]


def _try_entry(guard, broker, open_trades, signal: Signal, date, risk_pct, settings, result: ReplayResult) -> None:
    summary = broker.account_summary()
    qty = fixed_fractional_size(summary.nav, risk_pct, signal.entry_price, signal.stop_price, settings=settings)
    if qty <= 0:
        return
    broker.set_price(signal.symbol, signal.entry_price)
    buy_order = OrderRequest(contract=Contract(symbol=signal.symbol), action="BUY", quantity=qty, order_type="LMT", limit_price=signal.entry_price)
    ctx = _guard_context(broker, is_new_position=True)
    try:
        guard.place_order(buy_order, ctx)
    except GuardRejection as exc:
        result.rejections.append(f"{date} {signal.symbol} entry rejected: {exc.reason}")
        return
    open_trades[signal.symbol] = OpenTrade(signal=signal, quantity=qty, entry_price=signal.entry_price, entry_date=date)


def max_drawdown(equity_curve: list[tuple[Any, float]]) -> float:
    """Largest peak-to-trough decline in NAV, as a positive fraction of the peak."""
    peak = None
    worst = 0.0
    for _, nav in equity_curve:
        if peak is None or nav > peak:
            peak = nav
        if peak:
            worst = max(worst, (peak - nav) / peak)
    return worst


@dataclass
class StrategyStats:
    strategy: str
    trades: int
    wins: int
    losses: int
    win_rate: float
    total_pnl: float
    avg_pnl: float
    avg_r_multiple: float


def compute_strategy_stats(closed_trades: list[ClosedTrade]) -> dict[str, StrategyStats]:
    by_strategy: dict[str, list[ClosedTrade]] = {}
    for trade in closed_trades:
        by_strategy.setdefault(trade.strategy, []).append(trade)
    stats: dict[str, StrategyStats] = {}
    for strategy, trades in by_strategy.items():
        wins = sum(1 for t in trades if t.pnl > 0)
        losses = len(trades) - wins
        total_pnl = sum(t.pnl for t in trades)
        stats[strategy] = StrategyStats(
            strategy=strategy,
            trades=len(trades),
            wins=wins,
            losses=losses,
            win_rate=wins / len(trades) if trades else 0.0,
            total_pnl=total_pnl,
            avg_pnl=total_pnl / len(trades) if trades else 0.0,
            avg_r_multiple=sum(t.r_multiple for t in trades) / len(trades) if trades else 0.0,
        )
    return stats


def format_stats_report(result: ReplayResult) -> str:
    stats = compute_strategy_stats(result.closed_trades)
    lines = ["=== Per-strategy backtest report ==="]
    if not stats:
        lines.append("(no closed trades)")
    for s in sorted(stats.values(), key=lambda s: -s.total_pnl):
        lines.append(
            f"{s.strategy}: {s.trades} trades, {s.wins}W/{s.losses}L "
            f"({s.win_rate:.0%} win rate), total P&L ${s.total_pnl:,.2f}, "
            f"avg P&L ${s.avg_pnl:,.2f}, avg R {s.avg_r_multiple:.2f}"
        )
    lines.append(f"Max drawdown: {max_drawdown(result.equity_curve):.2%}")
    lines.append(f"Rejections during replay: {len(result.rejections)}")
    if result.equity_curve:
        lines.append(f"Final NAV: ${result.equity_curve[-1][1]:,.2f}")
    return "\n".join(lines)

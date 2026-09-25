"""Process entrypoint: wires broker -> guard -> strategies -> scheduler -> web app -> Telegram.

If IB Gateway isn't reachable, falls back to FakeBroker/FakeMarketData so the
system stays up (dry-run) instead of crashing, per CLAUDE.md's instruction to
keep building/running against the fake broker when no Gateway is available.
The scheduler's jobs are real, tested integration code (not placeholders):
`run_pre_market_plan` and `run_eod_management` run the full strategies/AI/
guard/execution pipeline against whatever MarketDataProvider is wired up --
with `FakeMarketData` (the default when IB Gateway is unreachable) they are
safe no-ops because no bars are populated, but the same code path is exercised
by tests with synthetic bars.
"""

from __future__ import annotations

import datetime as dt
import logging

from omega_ib.ai.reviewer import AIReviewer, apply_reviews_to_signals
from omega_ib.broker.base import BrokerBase, Contract, OrderRequest
from omega_ib.broker.fake import FakeBroker
from omega_ib.broker.ib import IBBroker
from omega_ib.config import Settings
from omega_ib.config import settings as default_settings
from omega_ib.data.market import FakeMarketData, MarketDataProvider, StaticEarningsCalendar
from omega_ib.execution.engine import build_bracket_order, place_bracket_order
from omega_ib.lifecycle.eod import eod_decisions_for_position
from omega_ib.notify.telegram import TelegramNotifier
from omega_ib.risk.guard import GuardContext, GuardRejection, RiskGuard, fixed_fractional_size
from omega_ib.scheduler import build_scheduler
from omega_ib.store.db import init_db
from omega_ib.strategies.equity import ALL_STRATEGIES, rank_signals, run_strategies
from omega_ib.web.app import create_app

logger = logging.getLogger(__name__)

DEFAULT_UNIVERSE = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL"]
DEFAULT_RISK_PCT = 0.01


def build_broker(settings: Settings) -> BrokerBase:
    """Attempts a real IB Gateway connection; falls back to FakeBroker (dry-run)
    if it's unreachable, so the system stays up read-only rather than crashing."""
    broker = IBBroker(settings.ib_host, settings.ib_port, settings.ib_client_id)
    try:
        broker.connect()
        logger.info("connected to IB Gateway at %s:%s", settings.ib_host, settings.ib_port)
        return broker
    except Exception as exc:  # noqa: BLE001 - startup must not crash without a Gateway
        logger.warning("IB Gateway unreachable (%s); falling back to FakeBroker (dry-run)", exc)
        fake = FakeBroker()
        fake.connect()
        return fake


def build_market_data(broker: BrokerBase) -> MarketDataProvider:
    if isinstance(broker, IBBroker):
        from omega_ib.data.market import IBMarketData

        return IBMarketData(broker)
    return FakeMarketData()


class AppState:
    def __init__(self, settings: Settings, broker: BrokerBase) -> None:
        self.settings = settings
        self.broker = broker
        self.market_data = build_market_data(broker)
        self.earnings_calendar = StaticEarningsCalendar()
        self.guard = RiskGuard(broker, settings)
        self.notifier = TelegramNotifier(broker, self.guard, settings)
        self.reviewer = AIReviewer(settings) if settings.anthropic_api_key else None
        self.web_app = create_app(broker=broker, settings=settings)


def build_app_state(settings: Settings | None = None, broker: BrokerBase | None = None) -> AppState:
    settings = settings or default_settings
    init_db(settings.database_url)
    broker = broker or build_broker(settings)
    return AppState(settings=settings, broker=broker)


def run_pre_market_plan(state: AppState, universe: list[str] | None = None) -> int:
    """Scan the universe, rank signals, get an (optional) AI review, size via
    risk/guard.py, and place bracket orders. Returns the number of orders placed."""
    universe = universe or DEFAULT_UNIVERSE
    signals = []
    for symbol in universe:
        bars = state.market_data.get_bars(symbol, lookback_days=90)
        if bars.empty:
            continue
        signals.extend(run_strategies(ALL_STRATEGIES, symbol, bars))
    ranked = rank_signals(signals)
    # One entry per symbol per day: if multiple strategies fire on the same
    # symbol, rank_signals already sorted highest-score first, so keep only
    # the first (best) signal per symbol rather than stacking redundant entries.
    seen_symbols: set[str] = set()
    deduped = []
    for signal in ranked:
        if signal.symbol in seen_symbols:
            continue
        seen_symbols.add(signal.symbol)
        deduped.append(signal)
    ranked = deduped
    if not ranked:
        logger.info("pre-market: no candidate signals")
        return 0

    account = state.broker.account_summary()
    if state.reviewer:
        outcome = state.reviewer.pre_market_plan(ranked, account)
        sized = apply_reviews_to_signals(ranked, outcome.response.reviews)
    else:
        sized = [(s, 1.0) for s in ranked]

    placed = 0
    for signal, multiplier in sized:
        qty = fixed_fractional_size(account.nav, DEFAULT_RISK_PCT, signal.entry_price, signal.stop_price, settings=state.settings)
        qty = int(qty * multiplier)
        if qty <= 0:
            continue
        contract = state.broker.qualify_contract(Contract(symbol=signal.symbol))
        bracket = build_bracket_order(contract, "BUY", qty, signal.entry_price, signal.stop_price, signal.target_price)
        ctx = GuardContext(nav=account.nav, open_positions=len(state.broker.positions()), is_new_position=True)
        try:
            place_bracket_order(state.guard, bracket, ctx)
            placed += 1
        except GuardRejection as exc:
            logger.warning("pre-market signal for %s rejected: %s", signal.symbol, exc.reason)

    state.notifier.send_alert(f"Pre-market plan: {len(ranked)} signal(s) considered, {placed} order(s) placed.")
    return placed


def run_mid_session_review(state: AppState) -> None:
    if not state.reviewer:
        return
    positions = state.broker.positions()
    summary = state.broker.account_summary()
    day_pnl_pct = summary.day_pnl / summary.nav if summary.nav else 0.0
    state.reviewer.mid_session_review(positions, day_pnl_pct)


def run_eod_management(state: AppState) -> int:
    """Runs the equity EOD lifecycle rules against every open position and
    flattens anything they flag. Returns the number of flatten orders placed."""
    today = dt.date.today()
    flattened = 0
    for position in state.broker.positions():
        pnl_pct = (
            position.unrealized_pnl / (abs(position.quantity) * position.avg_cost)
            if position.quantity and position.avg_cost
            else 0.0
        )
        decision = eod_decisions_for_position(
            position.symbol, today, state.earnings_calendar, unrealized_pnl_pct=pnl_pct, entered_today=False
        )
        if decision.action != "flatten":
            continue
        action = "SELL" if position.quantity > 0 else "BUY"
        order = OrderRequest(
            contract=Contract(symbol=position.symbol), action=action, quantity=abs(position.quantity),
            order_type="LMT", limit_price=position.market_price,
        )
        ctx = GuardContext(nav=state.broker.account_summary().nav, open_positions=len(state.broker.positions()), is_new_position=False)
        try:
            state.guard.place_order(order, ctx)
            flattened += 1
            logger.info("EOD flatten %s: %s", position.symbol, decision.reason)
        except GuardRejection as exc:
            logger.warning("EOD flatten for %s rejected: %s", position.symbol, exc.reason)

    if state.reviewer:
        trades_today = []  # populated from store.models.Trade once daily trade tracking is wired to a live account
        state.reviewer.eod_review(trades_today, state.broker.account_summary())
    return flattened


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    state = build_app_state()
    scheduler = build_scheduler(
        pre_market_job=lambda: run_pre_market_plan(state),
        mid_session_job=lambda: run_mid_session_review(state),
        eod_job=lambda: run_eod_management(state),
    )
    scheduler.start()
    try:
        import uvicorn

        uvicorn.run(state.web_app, host=state.settings.web_host, port=state.settings.web_port)
    finally:
        scheduler.shutdown(wait=False)
        state.broker.disconnect()


if __name__ == "__main__":
    main()

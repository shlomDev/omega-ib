# Progress

## Done
- Phase 1: Scaffold, config, fake broker, store, CI, .env.example
  - `pyproject.toml` with `[dev]` extra (pytest, pytest-asyncio, ruff)
  - `omega_ib/config.py`: pydantic-settings, TradingMode enum, live-trading gate
    (`live_trading_authorized` requires TRADING_MODE=live AND exact LIVE_CONFIRM phrase),
    `is_read_only`, `kill_switch_active`, hard risk limits with validators that
    reject `allow_naked_short_calls=True` / `allow_market_orders_options=True` outright.
  - `omega_ib/broker/base.py`: `BrokerBase` ABC + `Contract`/`OrderRequest`/`OrderStatus`/
    `Position`/`AccountSummary` dataclasses shared by fake and (future) IB broker.
  - `omega_ib/broker/fake.py`: in-memory `FakeBroker` — fills orders immediately at
    limit price (or settable mock price), tracks positions/cash/NAV/realized PnL.
  - `omega_ib/store/models.py`: SQLAlchemy models — Signal, Order, Fill, Trade,
    AIDecision, AuditLog, DailySnapshot.
  - `omega_ib/store/db.py`: engine/session factory (StaticPool for in-memory sqlite
    used by tests), `write_audit()` helper.
  - `.env.example` covering all settings.
  - Tests: `tests/test_config.py`, `tests/test_fake_broker.py`, `tests/test_store.py`.
  - `ruff check .` and `pytest -q` both green (11 passed).

- Phase 2: IB connection + reconnect + read-only snapshot
  - `omega_ib/broker/ib.py`: `IBBroker(BrokerBase)` wrapping `ib_async.IB` — connect/
    disconnect, `reconnect_with_backoff()` (exponential backoff), `heartbeat()`
    (via `reqCurrentTime`, never raises), `qualify_contract`, `place_order`,
    `cancel_order`/`cancel_all` (`reqGlobalCancel`), `positions()` (via `ib.portfolio()`),
    `account_summary()`, `open_orders()`. Registers `disconnectedEvent`/`errorEvent`
    handlers for logging.
  - Pure conversion helpers (`_to_ib_contract`, `_to_ib_order`, `_parse_account_summary`,
    `_portfolio_item_to_position`, `_trade_to_status`) built and unit-tested directly
    against in-process `ib_async` objects — no network needed.
  - `Contract` dataclass (broker/base.py) extended with `leg_action`/`leg_ratio` so BAG
    combo legs (needed by options_builder.py in phase 6) can be expressed.
  - `omega_ib/tools/check_connection.py`: read-only CLI smoke test (connect, print
    account summary + positions + open orders, disconnect). Never places orders.
  - Tests: `tests/test_ib_broker.py` (contract/order/account/position/status conversion),
    `tests/test_ib_broker_reconnect.py` (reconnect backoff + heartbeat via mocked `IB`).
  - `ruff check .` and `pytest -q` both green (25 passed).

- Phase 3: risk guard + kill switch + audit log
  - `omega_ib/risk/guard.py`: `RiskGuard` is the only sanctioned caller of
    `broker.place_order` (enforced by `tests/test_guard_enforcement.py`, which greps
    all of `omega_ib/` for `.place_order(` calls outside this one file). Every hard
    limit from CLAUDE.md rule 4 is a separate check: kill switch, read-only trading
    mode (live requires TRADING_MODE=live AND LIVE_CONFIRM=I_ACCEPT_REAL_MONEY_RISK),
    no market orders on options, no naked short calls (single-leg OPT SELL C checked
    against held shares; BAG legs checked so short calls can't exceed matching long
    calls in the structure), max options contracts/order, max order notional, max
    position % NAV, max open positions (only for genuinely new symbols), max daily
    loss % NAV, and a PDT day-trade check for sub-$25k NAV accounts. Every rejection
    and every placed order writes to the audit log with a reason (rule 7).
  - Kill switch: `engage_kill_switch()` touches the `KILL` file and calls
    `broker.cancel_all()`; `reset_kill_switch()` removes the file. `kill_switch_active`
    also honors the file existing already (so `touch KILL` from the CLI/Telegram/UI works).
  - Sizing helpers also live here per the CLAUDE.md layout comment:
    `fixed_fractional_size` (risk % of NAV per stop distance, capped by
    max_order_notional/max_position_pct_nav so a sizing bug can't itself breach a
    limit), `atr_stop_price`, `size_by_fixed_fractional_atr`.
  - Tests: `tests/test_guard_enforcement.py` (grep enforcement), `tests/test_risk_guard.py`
    (every limit, kill switch engage/reset, live-mode gating, sizing helpers) — 50 passed.

## In progress
- (none)

## Blocked
- No IB Gateway reachable in this dev/CI sandbox (carried over from Phase 2). All guard
  and sizing logic is broker-agnostic and fully tested against `FakeBroker`.

## Next
- Phase 4: `web/app.py` (FastAPI REST + WS), `web/static/index.html` (dark terminal UI),
  `risk/portfolio.py` (aggregate greeks/beta-weighted delta/sector concentration/VaR),
  `notify/telegram.py` (alerts + /status /pnl /positions /risk /scan /opts /kill /resume).

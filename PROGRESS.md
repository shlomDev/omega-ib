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

## In progress
- (none)

## Blocked
- No IB Gateway available in this environment. Phase 2 (broker/ib.py) will be built
  against the `ib_async` API and unit-tested with mocks; true live-integration
  checks against a running IB Gateway are marked pending until run on the VM/paper account.

## Next
- Phase 2: `broker/ib.py` (connect/reconnect/heartbeat/qualify/orders/positions/PnL),
  `tools/check_connection.py`.

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

- Phase 4: portfolio/risk terminal (read-only) + WS + Telegram alerts
  - `omega_ib/risk/portfolio.py`: `PositionRisk` (delta already in share terms so
    stocks and options aggregate uniformly), `aggregate_greeks`, `beta_weighted_delta_vs_spy`
    (SPY-equivalent dollar-delta), `sector_concentration`/`underlying_concentration`,
    `historical_var` (percentile of a daily-return sample), `RiskLimitGauge` +
    `daily_loss_gauge`/`open_positions_gauge` for UI distance-to-cap bars. Options
    greeks are optional fields that stay zero until data/options.py exists (phase 6).
  - `omega_ib/web/app.py`: FastAPI app (`create_app(broker, settings)` factory so
    tests/dry-run inject `FakeBroker`), single bearer-token auth (`web_auth_token`)
    on every `/api/*` route except `/api/health`. Endpoints: account, positions,
    open orders, risk/limits (with distance-to-daily-loss-cap and kill-switch state),
    audit feed, `POST /api/kill` / `POST /api/resume` (both go through `RiskGuard`,
    same path as Telegram/CLI), `/ws` WebSocket streaming account+positions+kill-switch
    snapshots every `ws_broadcast_interval_seconds`, and `/` serving the static UI.
    Still strictly read-only re: order placement -- no route can call place_order.
  - `omega_ib/web/static/index.html`: single-file dark-terminal UI (mobile-first) --
    token gate (localStorage), account/risk panels with gauge bars, positions/orders
    tables, audit feed, TradingView Lightweight Charts equity-curve placeholder, a
    `/kill` button wired to `POST /api/kill`, and WS auto-reconnect. Manually smoke
    tested by running a real uvicorn server and curling `/`, `/api/account`,
    `/api/risk/limits` (see commit); full browser interaction untested (no GUI here).
  - `omega_ib/notify/telegram.py`: `TelegramNotifier.send_alert` (no-ops with a log
    line when unconfigured -- safe in CI) and `handle_command` implementing
    `/status /pnl /positions /risk /kill /resume` (`/scan` `/opts` reply "not
    available yet" until phases 5/6 land). `/kill` and `/resume` call `RiskGuard`
    directly, same as the Web UI button.
  - Added `ws_broadcast_interval_seconds` to config.py.
  - Tests: `tests/test_portfolio_risk.py`, `tests/test_web_app.py` (FastAPI
    TestClient incl. WS auth + streaming), `tests/test_telegram.py`. 82 passed, ruff clean.

- Phase 5: equity strategies + scanner + execution + EOD
  - `omega_ib/strategies/equity/base.py`: `Strategy` ABC (`generate(symbol, bars) ->
    Signal | None`), `Signal` dataclass, `run_strategies`/`rank_signals` (highest
    score first). `indicators.py`: pure-pandas `sma`/`atr`/`vwap`/`rolling_high`/
    `rolling_low`/`zscore` shared by all five strategies.
  - Five pluggable strategies, each returning `None` when no setup or a `Signal`
    with entry/stop/target computed via `risk.guard.atr_stop_price`:
    `momentum_breakout.py` (close breaks prior N-day high on above-average volume),
    `gap_and_go.py` (morning gap holds above its own open), `mean_reversion.py`
    (oversold z-score bounce with a reversal candle), `vwap_reclaim.py` (price
    dips below VWAP then reclaims it), `trend_pullback.py` (pullback to 20d SMA
    within an uptrend defined by the 50d SMA, then bounces). Registered in
    `strategies/equity/__init__.py` as `ALL_STRATEGIES`.
  - `omega_ib/data/market.py`: `MarketDataProvider` ABC, `FakeMarketData`
    (in-memory bars/scan results for tests/dry-run), `IBMarketData` (wraps
    `ib_async` `reqHistoricalData`/`reqScannerData`; pure `_bars_to_dataframe`
    helper unit tested without network), `StaticEarningsCalendar` (dict-backed;
    swappable for a real feed later), `universe_from_scans` (de-duped union
    across multiple scanner subscriptions).
  - `omega_ib/execution/engine.py`: `build_bracket_order`/`place_bracket_order`
    (entry LMT + STP loss + LMT target, OCA-linked via `parent_id` once the entry
    is placed), `submit_with_price_walk` (cancel+resubmit a limit order up to
    `max_steps` times, walking price toward the market -- reusable for options
    combo orders once options_builder.py exists), `FillTracker` (idempotent
    fill ledger keyed by order_id, writes to the audit log). Every order placement
    goes through `guard.place_order(...)`, never the broker directly -- verified
    by the same grep-based enforcement test from Phase 3 (had to correct that
    test's pattern to `broker.place_order(` specifically, since it was originally
    over-broad and would have flagged the sanctioned `guard.place_order(...)` calls
    made from this module).
  - `omega_ib/lifecycle/eod.py`: equity-side EOD rules -- `leveraged_etf_flatten_decision`
    (never hold leveraged/inverse ETFs overnight), `earnings_proximity_decision`
    (flatten within N days of an earnings print), `overnight_hold_decision`
    (flatten a same-day entry already beyond a max intraday loss threshold),
    combined in `eod_decisions_for_position`. Options 21-DTE/50%-profit management
    is deferred to alongside phase 6 (needs options positions to exist first).
  - Tests: `tests/test_equity_indicators.py`, `tests/test_equity_strategies.py`
    (exact synthetic-bar fixtures verified against each strategy's real output
    before being written into assertions), `tests/test_market_data.py`,
    `tests/test_execution_engine.py` (incl. a scripted broker stub to exercise
    the price-walk retry loop, since `FakeBroker` always fills immediately),
    `tests/test_lifecycle_eod.py`. 125 tests green, ruff clean.

- Fixed a real bug found while staging this phase: `.gitignore`'s unanchored `data/`
  rule matched *any* directory named `data`, so `omega_ib/data/` (this phase's new
  package) was silently excluded from git entirely. Changed to `/data/` so only the
  repo-root sqlite/data directory is ignored. Verified `git ls-files` now includes
  `omega_ib/data/__init__.py` and `omega_ib/data/market.py`.

- Phase 6: options data, strategy builder, scanner, combo orders
  - `omega_ib/data/options.py`: `OptionQuote` (mid/spread_pct), `is_liquid`
    (spread% + open-interest filter, CLAUDE.md's "reject illiquid: bid-ask > X%
    of mid"), `OptionChain` (expiries/by_expiry/find/liquid_quotes), `iv_rank`/
    `iv_percentile`, `OptionsDataProvider` ABC with `FakeOptionsData` (in-memory,
    for tests/dry-run) and `IBOptionsData` (wraps ib_async's
    reqSecDefOptParams/reqTickers/modelGreeks -- untested end-to-end, no Gateway
    here; no IV-history feed wired up yet so `iv_history` returns `[]`).
  - `omega_ib/strategies/options/base.py`: `OptionsStrategy` ABC
    (`generate(chain, expiry) -> OptionStructure | None`), `OptionLeg`/
    `OptionStructure`, `nearest_by_delta` (liquid-quote delta-nearest selection,
    shared by every strategy below). Seven strategy files covering all eight
    types from CLAUDE.md feature B: `cash_secured_put.py`, `covered_call.py`
    (single short leg each -- risk/guard.py's covered-call check verifies
    shares/coverage independently), `bull_put_spread.py`/`bear_call_spread.py`
    (short + protective long leg, same expiry), `iron_condor.py` (composes the
    two credit spreads), `calendar_spread.py` (short near-term + long next-expiry,
    same strike/right), `debit_spreads.py` (`LongCallDebitSpread`/
    `LongPutDebitSpread`, long near-ATM + short further-OTM). Registered as
    `ALL_OPTIONS_STRATEGIES` in `strategies/options/__init__.py`.
  - `omega_ib/options_builder.py`: `build_combo_order` (structure -> BAG
    `Contract` + `OrderRequest`, action/limit_price derived from `net_price`'s
    sign convention: negative = credit, positive = debit), `net_greeks`,
    `payoff_at_expiration`/`payoff_curve` (for the UI payoff chart),
    `probability_of_profit` (retail delta-proxy heuristic: `1 - avg(|short
    delta|)` for credit structures, `avg(|long delta|)` for debit), `EV`,
    `return_on_risk`, `is_liquid_structure`, `score_structure`/`rank_structures`
    (EV + POP + theta + capped ROR, illiquid structures filtered out before
    scoring). Found and fixed a duplicate-breakeven bug in the sign-change scan
    while verifying against a synthetic chain (see `payoff_curve`/`summarize_payoff`
    zip logic: switched to a strict `pnl1 * pnl2 < 0` sign-change test).
  - `omega_ib/lifecycle/eod.py` gained `days_to_expiration` and
    `options_management_decision`: take-profit at 50% of max credit, stop-loss
    at 2x credit received (credit structures only -- CLAUDE.md's "2x credit"
    rule doesn't define an analogous debit-side threshold, so debit structures
    only get take-profit + the 21-DTE roll check), and exit/roll at 21 DTE.
  - Combo orders flow through the exact same `execution/engine.py`/
    `risk/guard.py` path as equities (verified in
    `tests/test_options_integration.py`): the naked-short-call guard check
    correctly passes covered spreads (long call caps the short) and blocks
    single-leg naked calls; `max_options_contracts_per_order` applies to combo
    quantity too.
  - Every numeric test fixture (`tests/options_fixtures.py`'s synthetic chain,
    and each strategy's expected strikes/breakevens/scores) was computed by
    running the real code first and reading back its actual output, not
    hand-calculated, to avoid encoding a wrong expectation.
  - Tests: `test_options_data.py`, `test_options_strategies.py`,
    `test_options_builder.py`, `test_options_management.py`,
    `test_options_integration.py`. 172 tests green, ruff clean.

## In progress
- (none)

## Blocked
- No IB Gateway reachable in this dev/CI sandbox (carried over from Phase 2). All
  strategy/execution/EOD/options logic is broker-agnostic and fully tested against
  `FakeBroker`/`FakeMarketData`/`FakeOptionsData`; `IBMarketData` and `IBOptionsData`'s
  live calls are untested end-to-end until run against a reachable Gateway.
- No browser/GUI available to visually test `web/static/index.html` (carried over
  from Phase 4).

## Next
- Phase 7: `ai/reviewer.py` -- Claude pre-market plan, mid-session review, EOD
  review; strict JSON schema output; fallback to rule-based operation when the
  API fails (system keeps running without AI). The AI layer stays strictly
  advisory per CLAUDE.md rule 5: propose/veto/tighten only, never loosen a limit
  or call the broker/guard directly.

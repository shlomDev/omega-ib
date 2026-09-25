# OMEGA-IB — Project Constitution for Claude Code

Autonomous IBKR trading system: equity autopilot + options scanner/strategy builder + live portfolio/risk terminal.
Owner: shlomDev. Target host: Oracle Cloud Ubuntu VM. Dev: Termux or VM over SSH.

## Non-negotiable safety rules
1. `TRADING_MODE=paper` is the default everywhere. Live requires `TRADING_MODE=live` AND `LIVE_CONFIRM=I_ACCEPT_REAL_MONEY_RISK` in `.env`. Missing either → refuse to start execution, run read-only.
2. Every order passes through `risk/guard.py`. Nothing else may call `broker.place_order`. Enforce with a test that greps the codebase.
3. Kill switch: `/kill` (Telegram + UI button + `touch KILL` file) cancels all open orders and blocks new ones until manually reset.
4. Hard limits (config, sane defaults): max daily loss 2% NAV, max position 10% NAV, max open positions 8, max order notional, max options contracts per order 10, no naked short calls, no market orders on options.
5. The AI layer (Claude API) is advisory. It can propose, veto, or tighten — never loosen a risk limit or bypass the guard.
6. Never commit secrets. `.env` is gitignored; ship `.env.example`.
7. Every order, fill, signal, AI decision, and guard rejection is written to the audit log (SQLite) with a reason.

## Stack
Python 3.11+, `ib_async` (maintained ib_insync fork), IB Gateway headless via Docker (`gnzsnz/ib-gateway` image, IBC handles login/2FA-restart),
FastAPI + WebSockets (terminal backend), single-file dark-terminal frontend (vanilla JS + TradingView Lightweight Charts),
SQLite via SQLAlchemy, APScheduler, `pandas_market_calendars`, `pydantic-settings`, `python-telegram-bot`, `anthropic` SDK, pytest.
Deploy: `docker-compose.yml` (gateway + app). Also a `systemd` unit for non-Docker runs.

## Layout
```
omega_ib/
  config.py            # pydantic settings, limits, mode
  broker/ib.py         # connect, auto-reconnect, heartbeat, contract qualify, orders, positions, PnL subs
  broker/fake.py       # in-memory fake broker for tests + dry-run
  data/market.py       # bars, snapshots, scanners (IB reqScannerSubscription), earnings calendar
  data/options.py      # chains, greeks, IV rank/percentile, liquidity filters (OI, spread %)
  strategies/equity/   # momentum breakout, gap-and-go, mean reversion, VWAP reclaim, trend pullback (pluggable Strategy base)
  strategies/options/  # CSP, covered call, bull put, bear call, iron condor, calendar, long call/put debit spread
  options_builder.py   # build combo (BAG) orders; compute max P/L, breakevens, POP, EV, greeks; payoff curve data
  risk/guard.py        # pre-trade checks, sizing (fixed-fractional + ATR), exposure, PDT, kill switch
  risk/portfolio.py    # aggregate delta/gamma/theta/vega, beta-weighted delta vs SPY, sector concentration, VaR (historical)
  execution/engine.py  # bracket orders equities, combo limit orders options with price-walk, fill tracking
  lifecycle/eod.py     # EOD rules: flatten leveraged ETFs, earnings-proximity exits, overnight-hold criteria, options 21-DTE / 50%-profit management
  ai/reviewer.py       # Claude pre-market plan, mid-session review, EOD review; strict JSON schema output
  notify/telegram.py   # alerts + commands: /status /pnl /positions /risk /scan /opts TICKER /kill /resume
  web/app.py           # FastAPI REST + WS streams
  web/static/index.html
  store/models.py      # trades, orders, signals, ai_decisions, audit, daily_snapshots
  scheduler.py         # pre-market 08:30 ET, open, intraday every N min, mid-session 12:30, EOD 15:40, post-close report
  main.py
tests/
backtest/replay.py     # replay historical bars through strategies + guard using fake broker
```

## Feature specs
**A. Equity autopilot (OMEGA on IBKR)** — pre-market scan (universe config + IB scanners), rank signals, AI plan, size via guard,
bracket orders (entry limit, stop, target), intraday trailing, mid-session AI review, EOD manager. Every decision logged.

**B. Options scanner + strategy builder** — per ticker or universe: IV rank, liquidity filter, generate candidate structures,
score by EV/POP/return-on-risk/theta, reject illiquid (bid-ask > X% of mid). Output ranked table + payoff chart.
One-click (UI) or `/opts` (Telegram) → preview → confirm → combo order through guard. Management rules: take profit 50%, exit/roll at 21 DTE, stop at 2x credit.

**C. Portfolio/risk terminal** — live account summary (NAV, day P&L, unrealized/realized), positions with per-row P&L and greeks,
portfolio greeks, beta-weighted delta, exposure by sector/underlying, margin usage, risk-limit gauges (distance to daily loss cap),
open orders, audit feed, equity curve from daily snapshots. Alerts (Telegram + UI) on limit breach, large move, fills, disconnects.
Mobile-first layout, dark terminal aesthetic. Auth: single bearer token from `.env`.

## Build phases (commit after each; all tests green before moving on)
1. Scaffold, config, fake broker, store, CI (GitHub Actions: ruff + pytest), `.env.example`, README.
2. IB connection + reconnect + read-only portfolio snapshot against paper. Script: `python -m omega_ib.tools.check_connection`.
3. Risk guard + kill switch + audit log. Tests for every limit.
4. Portfolio/risk terminal (C) read-only, WS live updates, Telegram alerts.
5. Equity strategies + scanner + execution + EOD (A) on fake broker, then paper.
6. Options data + builder + scanner (B), combo orders on paper.
7. AI reviewer with schema validation and fallback when API fails (system keeps running rule-based).
8. Backtest/replay harness + per-strategy stats report.
9. `docker-compose.yml` (gateway + app, reads `.env`) + systemd unit + deploy doc. Deployment runs via `.github/workflows/deploy.yml` (rsync + `docker compose up -d --build`). Hardening: rate-limit pacing for IB API, market-data subscription errors, weekend/holiday handling, daily gateway restart.

## CI/CD (already in the repo)
- `build.yml` runs you in GitHub Actions and chains itself until done. `ci.yml` runs ruff + pytest on every push. `deploy.yml` ships to the Oracle VM.
- NEVER modify anything under `.github/` (the token can't push workflow changes; the run will fail).
- Commit locally with clear messages; do NOT `git push` — the workflow pushes after you finish.
- Ship `pyproject.toml` with a `[dev]` extra (pytest, ruff) so CI can `pip install -e .[dev]`.

## Working rules for Claude Code
- Work autonomously through the phases. Don't ask for confirmation between phases; ask only if blocked on credentials or a real ambiguity.
- If IB Gateway isn't reachable, keep building against `broker/fake.py` and mark live-integration checks as pending in `PROGRESS.md`.
- Keep `PROGRESS.md` updated: done, in progress, blocked, next.
- Small, typed, tested modules. No placeholder `pass` functions left behind at phase end.

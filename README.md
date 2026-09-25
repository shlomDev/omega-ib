# OMEGA-IB
Autonomous IBKR trading system (equity autopilot, options builder, risk terminal). Spec: `CLAUDE.md`. State: `PROGRESS.md`. Deploying: `DEPLOY.md`.

## Safety
`TRADING_MODE=paper` by default everywhere. Going live requires *both*
`TRADING_MODE=live` and `LIVE_CONFIRM=I_ACCEPT_REAL_MONEY_RISK` in `.env` --
otherwise the system runs read-only. Every order passes through
`risk/guard.py` (nothing else may call the broker's `place_order`, enforced by
a test that greps the codebase). Kill switch: `touch KILL` in the working
directory, the Telegram `/kill` command, or the web UI's kill button -- all
three cancel every open order and block new ones until `/resume` or deleting
`KILL`.

## Running locally against the fake broker
No IB Gateway needed:
```bash
pip install -e ".[dev]"
pytest -q                     # 223 tests, all against FakeBroker/FakeMarketData/FakeOptionsData
python -m omega_ib.main       # falls back to FakeBroker if no Gateway is reachable
python -m omega_ib.tools.check_connection   # read-only smoke test against a real Gateway
```

## Actions
- **Autonomous build**: Claude Code builds the project, commits, and re-triggers itself until done. Telegram pings each run.
- **CI**: ruff + pytest on every push.
- **Deploy to Oracle VM**: rsync + `docker compose up -d --build`. Writes a paper-only `.env` on the VM the first time.

## Secrets (Settings → Secrets and variables → Actions)
Build: `ANTHROPIC_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`
Deploy: `VM_HOST`, `VM_USER`, `VM_SSH_KEY`, `TWS_USERID`, `TWS_PASSWORD` (PAPER account only)

Settings → Actions → General → Workflow permissions: **Read and write**.

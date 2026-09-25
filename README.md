# OMEGA-IB
Autonomous IBKR trading system (equity autopilot, options builder, risk terminal). Spec: `CLAUDE.md`. State: `PROGRESS.md`.

## Actions
- **Autonomous build**: Claude Code builds the project, commits, and re-triggers itself until done. Telegram pings each run.
- **CI**: ruff + pytest on every push.
- **Deploy to Oracle VM**: rsync + `docker compose up -d --build`. Writes a paper-only `.env` on the VM the first time.

## Secrets (Settings → Secrets and variables → Actions)
Build: `ANTHROPIC_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`
Deploy: `VM_HOST`, `VM_USER`, `VM_SSH_KEY`, `TWS_USERID`, `TWS_PASSWORD` (PAPER account only)

Settings → Actions → General → Workflow permissions: **Read and write**.

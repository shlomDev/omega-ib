# Deploying OMEGA-IB

Two supported paths: Docker Compose (recommended -- bundles IB Gateway) or a
bare-metal `systemd` unit against a Gateway you run/manage yourself.

Either way, start from `.env.example`:

```bash
cp .env.example .env
# fill in TWS_USERID / TWS_PASSWORD (paper account unless you really mean it),
# ANTHROPIC_API_KEY, TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID, and a random
# WEB_AUTH_TOKEN. Leave TRADING_MODE=paper and LIVE_CONFIRM empty unless you
# have read CLAUDE.md's safety rules and mean to go live.
```

## Option A: Docker Compose (gateway + app)

```bash
docker compose up -d --build
docker compose ps
docker compose logs -f app
```

This starts two services:
- **ib-gateway**: `gnzsnz/ib-gateway`, IBC-managed headless IB Gateway. Reads
  `TWS_USERID`/`TWS_PASSWORD`/`TRADING_MODE` from `.env`. IBC handles login and
  2FA-prompted restarts; `AUTO_RESTART_TIME` (default 11:59 PM) forces a daily
  restart at a quiet time so the Gateway doesn't accumulate stale connections
  over multi-day uptimes (part of the CLAUDE.md hardening checklist).
- **app**: this repo, built from `Dockerfile`. Waits for `ib-gateway`'s
  healthcheck, then runs `python -m omega_ib.main`, which:
  - connects to the Gateway at `IB_HOST=ib-gateway`/`IB_PORT` (falls back to an
    in-memory `FakeBroker` and logs a warning if the Gateway isn't reachable,
    rather than crashing -- useful for a first deploy before the Gateway has
    finished logging in);
  - starts the pre-market/mid-session/EOD job scheduler (skips weekends and
    NYSE holidays automatically);
  - serves the FastAPI terminal on `WEB_PORT` (default 8000), bound to
    `127.0.0.1` on the host -- put a reverse proxy with TLS in front of it if
    you need to reach it off-box.

`docker-compose.yml` mounts `./data` into the app container for the SQLite
audit/store database, and an `ib-gateway-data` volume for the Gateway's own
settings so it doesn't need to re-accept the API/IBC agreements every restart.

To ship a real update: `git pull && docker compose up -d --build`. The
repo's `deploy.yml` GitHub Action does exactly this over SSH (rsync + `docker
compose up -d --build`), writing a paper-only `.env` on the VM the first time
if one doesn't already exist.

## Option B: systemd (bring your own Gateway)

Use this if you're running IB Gateway/TWS directly on the host (or in its own
container/VM) rather than via this repo's compose file.

```bash
sudo mkdir -p /opt/omega-ib
sudo cp -r . /opt/omega-ib
cd /opt/omega-ib
python3 -m venv .venv
.venv/bin/pip install -e .
cp .env.example .env   # then edit it; IB_HOST/IB_PORT should point at your Gateway
sudo useradd --system --home /opt/omega-ib omega || true
sudo chown -R omega:omega /opt/omega-ib
sudo cp deploy/omega-ib.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now omega-ib
journalctl -u omega-ib -f
```

The unit runs as an unprivileged `omega` user with `ProtectSystem=strict` and
only `/opt/omega-ib/data` writable, restarts on failure, and reads its
configuration from `/opt/omega-ib/.env` (never commit that file -- see
`.gitignore`).

## Hardening notes (why these exist)

- **IB API rate-limit pacing**: `broker/ib.py`'s `IBBroker` runs every call
  through `broker/pacing.py`'s `RateLimiter` (40 calls/sec by default) so a
  burst of requests (e.g. qualifying many contracts during a scan) can't trip
  IB's own throttling/disconnect behavior.
- **Market-data subscription errors**: `IBBroker._on_error` recognizes IB's
  market-data-entitlement error codes (354, 2103, 2105, 2157, 10167, 10168)
  and sets `market_data_degraded = True` instead of logging them as fatal --
  a missing data subscription shouldn't take down order management.
- **Weekend/holiday handling**: `scheduler.py`'s `is_trading_day` (NYSE
  calendar via `pandas_market_calendars`) gates every scheduled job, so a cron
  firing on a Saturday or a market holiday is a documented no-op, not a bug.
- **Daily Gateway restart**: handled by IBC inside the `ib-gateway` container
  via `AUTO_RESTART_TIME` (see Option A) rather than by this app -- IBC is
  already the component responsible for the Gateway's own lifecycle/login.

## Secrets

Never commit `.env`. GitHub Actions secrets used by `deploy.yml`:
`VM_HOST`, `VM_USER`, `VM_SSH_KEY`, `TWS_USERID`, `TWS_PASSWORD` (paper account
only), plus whatever `build.yml` needs (`ANTHROPIC_API_KEY`,
`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`). See `README.md` for the full list.

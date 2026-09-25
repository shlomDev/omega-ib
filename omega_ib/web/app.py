"""FastAPI REST + WebSocket portfolio/risk terminal (feature C).

Read-only in this phase: no endpoint here can place, modify, or cancel an order --
that is risk/guard.py's job exclusively (CLAUDE.md rule 2). Auth is a single
bearer token from settings.web_auth_token (rule: "single bearer token from .env").
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Query, WebSocket, WebSocketDisconnect, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from omega_ib.broker.base import BrokerBase
from omega_ib.broker.fake import FakeBroker
from omega_ib.config import Settings
from omega_ib.config import settings as default_settings
from omega_ib.risk.guard import RiskGuard
from omega_ib.store.db import session_scope
from omega_ib.store.models import AuditLog

STATIC_DIR = Path(__file__).parent / "static"


def create_app(broker: BrokerBase | None = None, settings: Settings | None = None) -> FastAPI:
    app_settings = settings or default_settings
    app_broker = broker or FakeBroker()
    if not app_broker.is_connected:
        app_broker.connect()
    guard = RiskGuard(app_broker, app_settings)

    app = FastAPI(title="OMEGA-IB Terminal")
    app.state.broker = app_broker
    app.state.settings = app_settings
    app.state.guard = guard

    def verify_token(authorization: Annotated[str | None, Header()] = None) -> None:
        expected = f"Bearer {app.state.settings.web_auth_token}"
        if not authorization or authorization != expected:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid or missing token")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok", "connected": app.state.broker.is_connected}

    @app.get("/api/account", dependencies=[Depends(verify_token)])
    def account() -> dict:
        return asdict(app.state.broker.account_summary())

    @app.get("/api/positions", dependencies=[Depends(verify_token)])
    def positions() -> list[dict]:
        return [asdict(p) for p in app.state.broker.positions()]

    @app.get("/api/orders/open", dependencies=[Depends(verify_token)])
    def open_orders() -> list[dict]:
        return [asdict(o) for o in app.state.broker.open_orders()]

    @app.get("/api/risk/limits", dependencies=[Depends(verify_token)])
    def risk_limits() -> dict:
        summary = app.state.broker.account_summary()
        open_pos = app.state.broker.positions()
        s = app.state.settings
        day_pnl_pct = (summary.day_pnl / summary.nav) if summary.nav else 0.0
        return {
            "nav": summary.nav,
            "day_pnl_pct": day_pnl_pct,
            "max_daily_loss_pct_nav": s.max_daily_loss_pct_nav,
            "distance_to_daily_loss_cap_pct": s.max_daily_loss_pct_nav + day_pnl_pct,
            "open_positions": len(open_pos),
            "max_open_positions": s.max_open_positions,
            "max_position_pct_nav": s.max_position_pct_nav,
            "max_order_notional": s.max_order_notional,
            "max_options_contracts_per_order": s.max_options_contracts_per_order,
            "kill_switch_active": app.state.guard.kill_switch_active,
            "trading_mode": s.trading_mode,
            "is_read_only": s.is_read_only,
        }

    @app.get("/api/audit", dependencies=[Depends(verify_token)])
    def audit(limit: Annotated[int, Query(le=500)] = 50) -> list[dict]:
        with session_scope() as session:
            rows = session.query(AuditLog).order_by(AuditLog.id.desc()).limit(limit).all()
            return [
                {
                    "id": r.id,
                    "created_at": r.created_at.isoformat(),
                    "event_type": r.event_type,
                    "reason": r.reason,
                    "detail": r.detail,
                }
                for r in rows
            ]

    @app.post("/api/kill", dependencies=[Depends(verify_token)])
    def kill() -> dict:
        app.state.guard.engage_kill_switch("Web UI /kill button")
        return {"kill_switch_active": True}

    @app.post("/api/resume", dependencies=[Depends(verify_token)])
    def resume() -> dict:
        app.state.guard.reset_kill_switch()
        return {"kill_switch_active": False}

    @app.websocket("/ws")
    async def ws_endpoint(websocket: WebSocket, token: str | None = None) -> None:
        if token != app.state.settings.web_auth_token:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
        await websocket.accept()
        try:
            while True:
                snapshot = {
                    "account": asdict(app.state.broker.account_summary()),
                    "positions": [asdict(p) for p in app.state.broker.positions()],
                    "kill_switch_active": app.state.guard.kill_switch_active,
                }
                await websocket.send_json(snapshot)
                await asyncio.sleep(app.state.settings.ws_broadcast_interval_seconds)
        except WebSocketDisconnect:
            pass

    return app


app = create_app()

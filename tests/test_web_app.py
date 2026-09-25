import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from omega_ib.broker.base import Contract, OrderRequest
from omega_ib.broker.fake import FakeBroker
from omega_ib.config import Settings
from omega_ib.web.app import create_app

TOKEN = "test-secret"


def _client(**overrides):
    settings = Settings(web_auth_token=TOKEN, ws_broadcast_interval_seconds=0.01, **overrides)
    broker = FakeBroker(starting_nav=100_000.0)
    app = create_app(broker=broker, settings=settings)
    return TestClient(app), broker


def test_health_no_auth_required():
    client, _ = _client()
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_account_requires_token():
    client, _ = _client()
    resp = client.get("/api/account")
    assert resp.status_code == 401


def test_account_with_token():
    client, _ = _client()
    resp = client.get("/api/account", headers={"Authorization": f"Bearer {TOKEN}"})
    assert resp.status_code == 200
    assert resp.json()["nav"] == 100_000.0


def test_positions_reflect_broker_state():
    client, broker = _client()
    broker.place_order(OrderRequest(contract=Contract(symbol="AAPL"), action="BUY", quantity=10, limit_price=100.0))
    resp = client.get("/api/positions", headers={"Authorization": f"Bearer {TOKEN}"})
    assert resp.status_code == 200
    assert resp.json()[0]["symbol"] == "AAPL"


def test_risk_limits_endpoint():
    client, _ = _client()
    resp = client.get("/api/risk/limits", headers={"Authorization": f"Bearer {TOKEN}"})
    body = resp.json()
    assert body["max_daily_loss_pct_nav"] == 0.02
    assert body["kill_switch_active"] is False


def test_kill_endpoint_engages_switch(tmp_path):
    client, broker = _client(kill_switch_file=str(tmp_path / "KILL"))
    resp = client.post("/api/kill", headers={"Authorization": f"Bearer {TOKEN}"})
    assert resp.status_code == 200
    assert resp.json()["kill_switch_active"] is True
    limits = client.get("/api/risk/limits", headers={"Authorization": f"Bearer {TOKEN}"}).json()
    assert limits["kill_switch_active"] is True


def test_resume_endpoint_resets_switch(tmp_path):
    client, broker = _client(kill_switch_file=str(tmp_path / "KILL"))
    client.post("/api/kill", headers={"Authorization": f"Bearer {TOKEN}"})
    resp = client.post("/api/resume", headers={"Authorization": f"Bearer {TOKEN}"})
    assert resp.json()["kill_switch_active"] is False


def test_audit_endpoint_returns_list():
    client, _ = _client()
    resp = client.get("/api/audit", headers={"Authorization": f"Bearer {TOKEN}"})
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_index_served():
    client, _ = _client()
    resp = client.get("/")
    assert resp.status_code == 200
    assert "OMEGA-IB" in resp.text


def test_ws_requires_valid_token():
    client, _ = _client()
    # server closes immediately with a policy violation before ever accepting
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws?token=wrong"):
            pass


def test_ws_streams_account_snapshot():
    client, _ = _client()
    with client.websocket_connect(f"/ws?token={TOKEN}") as ws:
        data = ws.receive_json()
        assert "account" in data
        assert "positions" in data
        assert data["account"]["nav"] == 100_000.0

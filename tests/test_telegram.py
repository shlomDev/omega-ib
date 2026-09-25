from omega_ib.broker.base import Contract, OrderRequest
from omega_ib.broker.fake import FakeBroker
from omega_ib.config import Settings
from omega_ib.notify.telegram import TelegramNotifier
from omega_ib.risk.guard import RiskGuard


def _notifier(tmp_path, **overrides):
    settings = Settings(kill_switch_file=str(tmp_path / "KILL"), **overrides)
    broker = FakeBroker(starting_nav=50_000.0)
    broker.connect()
    guard = RiskGuard(broker, settings)
    return TelegramNotifier(broker, guard, settings), broker, guard


def test_send_alert_without_config_does_not_raise(tmp_path):
    notifier, _, _ = _notifier(tmp_path)
    notifier.send_alert("test alert")  # no token/chat_id configured -> logs and returns


def test_status_command(tmp_path):
    notifier, _, _ = _notifier(tmp_path)
    reply = notifier.handle_command("/status")
    assert "NAV: $50,000.00" in reply
    assert "off" in reply


def test_pnl_command(tmp_path):
    notifier, _, _ = _notifier(tmp_path)
    reply = notifier.handle_command("/pnl")
    assert "Day P&L" in reply


def test_positions_command_empty(tmp_path):
    notifier, _, _ = _notifier(tmp_path)
    assert notifier.handle_command("/positions") == "No open positions."


def test_positions_command_with_holdings(tmp_path):
    notifier, broker, _ = _notifier(tmp_path)
    broker.place_order(OrderRequest(contract=Contract(symbol="AAPL"), action="BUY", quantity=10, limit_price=100.0))
    reply = notifier.handle_command("/positions")
    assert "AAPL" in reply


def test_risk_command(tmp_path):
    notifier, _, _ = _notifier(tmp_path)
    reply = notifier.handle_command("/risk")
    assert "Open positions: 0/8" in reply


def test_kill_command_engages_switch(tmp_path):
    notifier, _, guard = _notifier(tmp_path)
    reply = notifier.handle_command("/kill")
    assert "ENGAGED" in reply
    assert guard.kill_switch_active


def test_resume_command_resets_switch(tmp_path):
    notifier, _, guard = _notifier(tmp_path)
    notifier.handle_command("/kill")
    reply = notifier.handle_command("/resume")
    assert "resumed" in reply
    assert not guard.kill_switch_active


def test_scan_and_opts_not_yet_available(tmp_path):
    notifier, _, _ = _notifier(tmp_path)
    assert "not available yet" in notifier.handle_command("/scan AAPL").lower()
    assert "not available yet" in notifier.handle_command("/opts AAPL").lower()


def test_unknown_command(tmp_path):
    notifier, _, _ = _notifier(tmp_path)
    assert notifier.handle_command("/bogus") == "Unknown command. Try /status /pnl /positions /risk /kill /resume."

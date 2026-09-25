"""Reconnect/heartbeat behavior of IBBroker, exercised with mocks (no network)."""

from unittest.mock import MagicMock, patch

from omega_ib.broker.ib import IBBroker


def _broker() -> IBBroker:
    with patch("omega_ib.broker.ib.IB") as MockIB:
        MockIB.return_value = MagicMock()
        broker = IBBroker("127.0.0.1", 4002, 17)
    return broker


def test_reconnect_with_backoff_succeeds_first_try():
    broker = _broker()
    broker.connect = MagicMock()
    assert broker.reconnect_with_backoff(max_attempts=3, base_delay=0.0) is True
    broker.connect.assert_called_once()


def test_reconnect_with_backoff_gives_up_after_max_attempts():
    broker = _broker()
    broker.connect = MagicMock(side_effect=ConnectionError("no gateway"))
    assert broker.reconnect_with_backoff(max_attempts=3, base_delay=0.0) is False
    assert broker.connect.call_count == 3


def test_heartbeat_returns_false_on_error_without_raising():
    broker = _broker()
    broker.ib.reqCurrentTime = MagicMock(side_effect=ConnectionError("disconnected"))
    assert broker.heartbeat() is False


def test_heartbeat_returns_true_when_alive():
    broker = _broker()
    broker.ib.reqCurrentTime = MagicMock(return_value=None)
    assert broker.heartbeat() is True

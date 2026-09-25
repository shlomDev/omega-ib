"""Rate-limit pacing and market-data error handling in IBBroker -- no network,
IB() is patched out per the pattern in test_ib_broker_reconnect.py."""

from unittest.mock import MagicMock, patch

from omega_ib.broker.ib import MARKET_DATA_ERROR_CODES, IBBroker


def _broker() -> IBBroker:
    with patch("omega_ib.broker.ib.IB") as MockIB:
        MockIB.return_value = MagicMock()
        broker = IBBroker("127.0.0.1", 4002, 17)
    return broker


def test_pacer_acquire_called_before_account_summary():
    broker = _broker()
    broker.ib.accountSummary = MagicMock(return_value=[])
    broker._pacer.acquire = MagicMock(wraps=broker._pacer.acquire)
    broker.account_summary()
    broker._pacer.acquire.assert_called_once()


def test_market_data_error_sets_degraded_flag_without_raising():
    broker = _broker()
    assert broker.market_data_degraded is False
    code = next(iter(MARKET_DATA_ERROR_CODES))
    broker._on_error(1, code, "Requested market data is not subscribed.", None)
    assert broker.market_data_degraded is True


def test_non_market_data_error_does_not_set_degraded_flag():
    broker = _broker()
    broker._on_error(1, 502, "Couldn't connect to TWS", None)
    assert broker.market_data_degraded is False

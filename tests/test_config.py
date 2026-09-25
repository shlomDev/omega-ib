import pytest

from omega_ib.config import LIVE_CONFIRM_PHRASE, Settings, TradingMode


def test_paper_is_default():
    s = Settings()
    assert s.trading_mode == TradingMode.PAPER
    assert s.is_read_only is False


def test_live_requires_both_mode_and_confirm():
    s = Settings(trading_mode=TradingMode.LIVE, live_confirm="")
    assert s.live_trading_authorized is False
    assert s.is_read_only is True

    s = Settings(trading_mode=TradingMode.LIVE, live_confirm="wrong-phrase")
    assert s.live_trading_authorized is False
    assert s.is_read_only is True

    s = Settings(trading_mode=TradingMode.LIVE, live_confirm=LIVE_CONFIRM_PHRASE)
    assert s.live_trading_authorized is True
    assert s.is_read_only is False


def test_naked_short_calls_cannot_be_enabled():
    with pytest.raises(ValueError):
        Settings(allow_naked_short_calls=True)


def test_market_orders_on_options_cannot_be_enabled():
    with pytest.raises(ValueError):
        Settings(allow_market_orders_options=True)


def test_kill_switch_file_detection(tmp_path):
    kill_file = tmp_path / "KILL"
    s = Settings(kill_switch_file=str(kill_file))
    assert s.kill_switch_active is False
    kill_file.touch()
    assert s.kill_switch_active is True

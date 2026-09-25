import datetime as dt

import pandas as pd
from ib_async import BarData

from omega_ib.data.market import (
    FakeMarketData,
    ScanRankRequest,
    StaticEarningsCalendar,
    _bars_to_dataframe,
    universe_from_scans,
)


def test_fake_market_data_bars_roundtrip():
    provider = FakeMarketData()
    bars = pd.DataFrame({"open": [1, 2], "high": [1, 2], "low": [1, 2], "close": [1, 2], "volume": [10, 20]})
    provider.set_bars("AAPL", bars)
    result = provider.get_bars("AAPL")
    assert list(result["close"]) == [1, 2]


def test_fake_market_data_missing_symbol_returns_empty():
    provider = FakeMarketData()
    result = provider.get_bars("NOPE")
    assert result.empty
    assert list(result.columns) == ["open", "high", "low", "close", "volume"]


def test_fake_market_data_lookback_truncation():
    provider = FakeMarketData()
    bars = pd.DataFrame({"open": range(10), "high": range(10), "low": range(10), "close": range(10), "volume": range(10)})
    provider.set_bars("AAPL", bars)
    result = provider.get_bars("AAPL", lookback_days=3)
    assert len(result) == 3


def test_fake_market_data_scan():
    provider = FakeMarketData()
    provider.set_scan_result("TOP_GAINERS", ["AAPL", "MSFT", "TSLA"])
    assert provider.scan("TOP_GAINERS", number_of_rows=2) == ["AAPL", "MSFT"]
    assert provider.scan("UNKNOWN_SCAN") == []


def test_bars_to_dataframe_from_ib_bardata():
    bar_list = [
        BarData(date=dt.date(2026, 1, 2), open=100.0, high=101.0, low=99.0, close=100.5, volume=1000),
        BarData(date=dt.date(2026, 1, 3), open=100.5, high=102.0, low=100.0, close=101.5, volume=1200),
    ]
    df = _bars_to_dataframe(bar_list)
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    assert len(df) == 2
    assert df.iloc[-1]["close"] == 101.5


def test_bars_to_dataframe_empty():
    df = _bars_to_dataframe([])
    assert df.empty


def test_universe_from_scans_dedupes_and_preserves_order():
    provider = FakeMarketData()
    provider.set_scan_result("TOP_GAINERS", ["AAPL", "MSFT"])
    provider.set_scan_result("MOST_ACTIVE", ["MSFT", "TSLA"])
    requests = [ScanRankRequest(scan_code="TOP_GAINERS"), ScanRankRequest(scan_code="MOST_ACTIVE")]
    universe = universe_from_scans(provider, requests)
    assert universe == ["AAPL", "MSFT", "TSLA"]


def test_static_earnings_calendar():
    calendar = StaticEarningsCalendar()
    calendar.set_earnings_date("AAPL", dt.date(2026, 1, 30))
    assert calendar.days_until_earnings("AAPL", dt.date(2026, 1, 25)) == 5
    assert calendar.days_until_earnings("MSFT", dt.date(2026, 1, 25)) is None

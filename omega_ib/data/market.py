"""Bars, snapshots, scanners, and earnings-proximity data for the equity autopilot.

No IB Gateway is reachable in this sandbox: FakeMarketData is an in-memory
provider used for strategy/scanner tests and dry-run. IBMarketData wraps
ib_async's reqHistoricalData/reqScannerData; its pure conversion helper
(`_bars_to_dataframe`) is unit tested without network. True live scans/bars are
pending until run against a reachable Gateway (see PROGRESS.md).
"""

from __future__ import annotations

import datetime as dt
from abc import ABC, abstractmethod
from dataclasses import dataclass

import pandas as pd


class MarketDataProvider(ABC):
    @abstractmethod
    def get_bars(self, symbol: str, lookback_days: int = 60, bar_size: str = "1 day") -> pd.DataFrame: ...

    @abstractmethod
    def scan(
        self,
        scan_code: str,
        instrument: str = "STK",
        location_code: str = "STK.US.MAJOR",
        number_of_rows: int = 50,
    ) -> list[str]: ...


class FakeMarketData(MarketDataProvider):
    """In-memory bars/scan results, settable by tests and dry-run."""

    def __init__(self) -> None:
        self.bars: dict[str, pd.DataFrame] = {}
        self.scan_results: dict[str, list[str]] = {}

    def set_bars(self, symbol: str, bars: pd.DataFrame) -> None:
        self.bars[symbol] = bars

    def get_bars(self, symbol: str, lookback_days: int = 60, bar_size: str = "1 day") -> pd.DataFrame:
        bars = self.bars.get(symbol)
        if bars is None:
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        return bars.tail(lookback_days)

    def set_scan_result(self, scan_code: str, symbols: list[str]) -> None:
        self.scan_results[scan_code] = symbols

    def scan(
        self,
        scan_code: str,
        instrument: str = "STK",
        location_code: str = "STK.US.MAJOR",
        number_of_rows: int = 50,
    ) -> list[str]:
        return self.scan_results.get(scan_code, [])[:number_of_rows]


def _bars_to_dataframe(bar_list) -> pd.DataFrame:
    """Convert a list of ib_async BarData into our standard OHLCV DataFrame."""
    rows = [
        {"date": b.date, "open": b.open, "high": b.high, "low": b.low, "close": b.close, "volume": b.volume}
        for b in bar_list
    ]
    df = pd.DataFrame(rows, columns=["date", "open", "high", "low", "close", "volume"])
    if not df.empty:
        df = df.set_index("date")
    return df


class IBMarketData(MarketDataProvider):
    """Wraps the ib_async.IB instance owned by an IBBroker (broker/ib.py)."""

    def __init__(self, ib_broker) -> None:
        self._ib = ib_broker.ib

    def get_bars(self, symbol: str, lookback_days: int = 60, bar_size: str = "1 day") -> pd.DataFrame:
        from ib_async.contract import Stock

        contract = Stock(symbol, "SMART", "USD")
        bar_list = self._ib.reqHistoricalData(
            contract,
            endDateTime="",
            durationStr=f"{lookback_days} D",
            barSizeSetting=bar_size,
            whatToShow="TRADES",
            useRTH=True,
        )
        return _bars_to_dataframe(bar_list)

    def scan(
        self,
        scan_code: str,
        instrument: str = "STK",
        location_code: str = "STK.US.MAJOR",
        number_of_rows: int = 50,
    ) -> list[str]:
        from ib_async import ScannerSubscription

        sub = ScannerSubscription(
            instrument=instrument, locationCode=location_code, scanCode=scan_code, numberOfRows=number_of_rows
        )
        results = self._ib.reqScannerData(sub)
        return [r.contractDetails.contract.symbol for r in results]


class StaticEarningsCalendar:
    """Dict-backed earnings calendar. Swap for a real data feed later without changing callers."""

    def __init__(self, dates: dict[str, dt.date] | None = None) -> None:
        self._dates: dict[str, dt.date] = dict(dates or {})

    def set_earnings_date(self, symbol: str, date: dt.date) -> None:
        self._dates[symbol] = date

    def days_until_earnings(self, symbol: str, as_of: dt.date) -> int | None:
        earnings_date = self._dates.get(symbol)
        if earnings_date is None:
            return None
        return (earnings_date - as_of).days


@dataclass
class ScanRankRequest:
    scan_code: str
    instrument: str = "STK"
    location_code: str = "STK.US.MAJOR"
    number_of_rows: int = 50


def universe_from_scans(provider: MarketDataProvider, requests: list[ScanRankRequest]) -> list[str]:
    """Union of symbols across multiple scanner subscriptions, de-duplicated, order preserved."""
    seen: dict[str, None] = {}
    for req in requests:
        for symbol in provider.scan(req.scan_code, req.instrument, req.location_code, req.number_of_rows):
            seen.setdefault(symbol, None)
    return list(seen.keys())

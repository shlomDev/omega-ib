"""Shared indicator helpers for equity strategies. Pure pandas, no I/O."""

from __future__ import annotations

import pandas as pd


def sma(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window).mean()


def atr(bars: pd.DataFrame, window: int = 14) -> pd.Series:
    high, low, close = bars["high"], bars["low"], bars["close"]
    prev_close = close.shift(1)
    true_range = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    return true_range.rolling(window).mean()


def vwap(bars: pd.DataFrame) -> pd.Series:
    typical = (bars["high"] + bars["low"] + bars["close"]) / 3
    cum_vol = bars["volume"].cumsum()
    cum_vol_price = (typical * bars["volume"]).cumsum()
    return cum_vol_price / cum_vol


def rolling_high(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window).max()


def rolling_low(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window).min()


def zscore(series: pd.Series, window: int) -> pd.Series:
    mean = series.rolling(window).mean()
    std = series.rolling(window).std()
    return (series - mean) / std

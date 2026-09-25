import pandas as pd

from omega_ib.strategies.equity.indicators import atr, rolling_high, rolling_low, sma, vwap, zscore


def _bars(closes):
    n = len(closes)
    return pd.DataFrame(
        {
            "open": closes,
            "high": [c + 1 for c in closes],
            "low": [c - 1 for c in closes],
            "close": closes,
            "volume": [1000] * n,
        }
    )


def test_sma():
    s = sma(pd.Series([1, 2, 3, 4, 5]), window=3)
    assert s.iloc[-1] == 4.0


def test_atr_positive_for_moving_series():
    bars = _bars([100, 101, 102, 101, 103, 104])
    result = atr(bars, window=3)
    assert result.iloc[-1] > 0


def test_vwap_between_low_and_high():
    bars = _bars([100, 101, 102])
    vw = vwap(bars)
    assert bars["low"].iloc[-1] <= vw.iloc[-1] <= bars["high"].iloc[-1]


def test_rolling_high_low():
    s = pd.Series([1, 5, 3, 9, 2])
    assert rolling_high(s, 3).iloc[-1] == 9
    assert rolling_low(s, 3).iloc[-1] == 2


def test_zscore_extreme_drop():
    closes = [100] * 20 + [80]
    z = zscore(pd.Series(closes), window=20)
    assert z.iloc[-1] < -2

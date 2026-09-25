import pandas as pd

from omega_ib.strategies.equity import (
    ALL_STRATEGIES,
    GapAndGo,
    MeanReversion,
    MomentumBreakout,
    Signal,
    TrendPullback,
    VWAPReclaim,
    rank_signals,
    run_strategies,
)


def test_momentum_breakout_triggers_on_high_volume_breakout():
    rows = [dict(open=100, high=101, low=99, close=100, volume=1000) for _ in range(21)]
    rows.append(dict(open=104, high=110, low=100, close=108, volume=3000))
    bars = pd.DataFrame(rows)
    signal = MomentumBreakout().generate("TEST", bars)
    assert signal is not None
    assert signal.direction == "long"
    assert signal.entry_price == 108.0
    assert signal.stop_price < signal.entry_price < signal.target_price


def test_momentum_breakout_none_without_breakout():
    rows = [dict(open=100, high=101, low=99, close=100, volume=1000) for _ in range(22)]
    bars = pd.DataFrame(rows)
    assert MomentumBreakout().generate("TEST", bars) is None


def test_gap_and_go_triggers_on_held_gap():
    rows = [dict(open=100, high=101, low=99, close=100, volume=1000) for _ in range(15)]
    rows.append(dict(open=103, high=105, low=103, close=104, volume=1500))
    bars = pd.DataFrame(rows)
    signal = GapAndGo().generate("TEST", bars)
    assert signal is not None
    assert signal.entry_price == 104.0
    assert signal.stop_price == 101.0


def test_gap_and_go_none_without_gap():
    rows = [dict(open=100, high=101, low=99, close=100, volume=1000) for _ in range(15)]
    rows.append(dict(open=100, high=101, low=99, close=100.2, volume=1000))
    bars = pd.DataFrame(rows)
    assert GapAndGo().generate("TEST", bars) is None


def _mean_reversion_baseline():
    return [
        dict(open=100 + (0.1 if i % 2 == 0 else -0.1), high=100.5 + (0.1 if i % 2 == 0 else -0.1),
             low=99.5 + (0.1 if i % 2 == 0 else -0.1), close=100 + (0.1 if i % 2 == 0 else -0.1), volume=1000)
        for i in range(20)
    ]


def test_mean_reversion_triggers_on_oversold_bounce():
    rows = _mean_reversion_baseline()
    rows.append(dict(open=96, high=97, low=90, close=91, volume=1000))
    rows.append(dict(open=91, high=95, low=90, close=94, volume=1000))
    bars = pd.DataFrame(rows)
    signal = MeanReversion().generate("TEST", bars)
    assert signal is not None
    assert signal.entry_price == 94.0
    assert signal.target_price > signal.entry_price


def test_mean_reversion_none_when_flat():
    rows = _mean_reversion_baseline() + _mean_reversion_baseline()[:2]
    bars = pd.DataFrame(rows)
    assert MeanReversion().generate("TEST", bars) is None


def test_vwap_reclaim_triggers_after_dip_and_reclaim():
    rows = [dict(open=99, high=101, low=99, close=100, volume=1000) for _ in range(14)]
    rows.append(dict(open=99, high=99, low=97, close=98, volume=1000))
    rows.append(dict(open=98, high=102, low=98, close=101, volume=1000))
    bars = pd.DataFrame(rows)
    signal = VWAPReclaim().generate("TEST", bars)
    assert signal is not None
    assert signal.entry_price == 101.0


def test_vwap_reclaim_none_when_still_below():
    rows = [dict(open=99, high=101, low=99, close=100, volume=1000) for _ in range(14)]
    rows.append(dict(open=99, high=99, low=97, close=98, volume=1000))
    rows.append(dict(open=97, high=98, low=96, close=97, volume=1000))
    bars = pd.DataFrame(rows)
    assert VWAPReclaim().generate("TEST", bars) is None


def _uptrend_bars(n=51):
    closes = [80 + i * 0.9 for i in range(n)]
    return [dict(open=c - 0.3, high=c + 0.5, low=c - 0.5, close=c, volume=1000) for c in closes]


def test_trend_pullback_triggers_on_bounce_at_support():
    rows = _uptrend_bars()
    rows.append(dict(open=116.8, high=117.5, low=116.9, close=117.2, volume=1000))
    bars = pd.DataFrame(rows)
    signal = TrendPullback().generate("TEST", bars)
    assert signal is not None
    assert signal.entry_price == 117.2


def test_trend_pullback_none_in_downtrend():
    closes_down = [130 - i * 0.9 for i in range(52)]
    rows = [dict(open=c + 0.3, high=c + 0.5, low=c - 0.5, close=c, volume=1000) for c in closes_down]
    bars = pd.DataFrame(rows)
    assert TrendPullback().generate("TEST", bars) is None


def test_run_strategies_and_rank_signals():
    good_signal = Signal(symbol="A", strategy="s1", direction="long", score=1.0, entry_price=1, stop_price=0.9, target_price=1.2)
    better_signal = Signal(symbol="B", strategy="s2", direction="long", score=3.0, entry_price=1, stop_price=0.9, target_price=1.2)
    ranked = rank_signals([good_signal, better_signal])
    assert ranked[0].symbol == "B"
    assert ranked[1].symbol == "A"


def test_all_strategies_registered():
    assert len(ALL_STRATEGIES) == 5
    names = {s.name for s in ALL_STRATEGIES}
    assert names == {"momentum_breakout", "gap_and_go", "mean_reversion", "vwap_reclaim", "trend_pullback"}


def test_run_strategies_skips_none():
    flat_bars = pd.DataFrame([dict(open=100, high=101, low=99, close=100, volume=1000) for _ in range(60)])
    signals = run_strategies(ALL_STRATEGIES, "FLAT", flat_bars)
    assert signals == []

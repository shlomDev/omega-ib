"""Long when today's close breaks above the prior N-day high on above-average volume."""

from __future__ import annotations

import pandas as pd

from omega_ib.risk.guard import atr_stop_price
from omega_ib.strategies.equity.base import Signal, Strategy
from omega_ib.strategies.equity.indicators import atr, rolling_high


class MomentumBreakout(Strategy):
    name = "momentum_breakout"

    def __init__(
        self,
        lookback: int = 20,
        volume_multiple: float = 1.5,
        atr_multiplier: float = 2.0,
        target_r_multiple: float = 2.0,
    ) -> None:
        self.lookback = lookback
        self.volume_multiple = volume_multiple
        self.atr_multiplier = atr_multiplier
        self.target_r_multiple = target_r_multiple

    def generate(self, symbol: str, bars: pd.DataFrame) -> Signal | None:
        if len(bars) < self.lookback + 2:
            return None
        prior_high = rolling_high(bars["high"].shift(1), self.lookback).iloc[-1]
        last = bars.iloc[-1]
        avg_volume = bars["volume"].iloc[-(self.lookback + 1) : -1].mean()
        atr_val = atr(bars).iloc[-1]
        if pd.isna(prior_high) or pd.isna(atr_val) or atr_val <= 0 or pd.isna(avg_volume) or avg_volume <= 0:
            return None
        if last["close"] <= prior_high:
            return None
        if last["volume"] < avg_volume * self.volume_multiple:
            return None
        entry = float(last["close"])
        stop = atr_stop_price(entry, float(atr_val), self.atr_multiplier, "long")
        target = entry + (entry - stop) * self.target_r_multiple
        score = float((entry - prior_high) / atr_val)
        return Signal(
            symbol=symbol,
            strategy=self.name,
            direction="long",
            score=score,
            entry_price=entry,
            stop_price=stop,
            target_price=target,
            reason=f"breakout above {self.lookback}d high {prior_high:.2f} on {last['volume'] / avg_volume:.1f}x volume",
        )

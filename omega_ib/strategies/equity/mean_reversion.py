"""Long a short-term oversold bounce: price is statistically stretched below its
rolling mean and today's candle shows the first sign of a reversal."""

from __future__ import annotations

import pandas as pd

from omega_ib.risk.guard import atr_stop_price
from omega_ib.strategies.equity.base import Signal, Strategy
from omega_ib.strategies.equity.indicators import atr, sma, zscore


class MeanReversion(Strategy):
    name = "mean_reversion"

    def __init__(self, window: int = 20, entry_zscore: float = -2.0, atr_multiplier: float = 1.5) -> None:
        self.window = window
        self.entry_zscore = entry_zscore
        self.atr_multiplier = atr_multiplier

    def generate(self, symbol: str, bars: pd.DataFrame) -> Signal | None:
        if len(bars) < self.window + 2:
            return None
        z = zscore(bars["close"], self.window).iloc[-1]
        last = bars.iloc[-1]
        if pd.isna(z) or z > self.entry_zscore:
            return None
        if last["close"] <= last["open"]:  # require a reversal (green) candle
            return None
        atr_val = atr(bars).iloc[-1]
        if pd.isna(atr_val) or atr_val <= 0:
            return None
        entry = float(last["close"])
        stop = atr_stop_price(entry, float(atr_val), self.atr_multiplier, "long")
        target = float(sma(bars["close"], self.window).iloc[-1])
        if target <= entry or stop >= entry:
            return None
        score = float(-z)
        return Signal(
            symbol=symbol,
            strategy=self.name,
            direction="long",
            score=score,
            entry_price=entry,
            stop_price=stop,
            target_price=target,
            reason=f"oversold at {z:.2f} std devs below {self.window}d mean, reversal candle",
        )

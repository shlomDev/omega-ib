"""Long a pullback to the 20d SMA within an established uptrend (price above the 50d SMA)."""

from __future__ import annotations

import pandas as pd

from omega_ib.risk.guard import atr_stop_price
from omega_ib.strategies.equity.base import Signal, Strategy
from omega_ib.strategies.equity.indicators import atr, sma


class TrendPullback(Strategy):
    name = "trend_pullback"

    def __init__(
        self,
        fast_window: int = 20,
        slow_window: int = 50,
        support_tolerance_pct: float = 0.015,
        atr_multiplier: float = 1.0,
        target_r_multiple: float = 2.0,
    ) -> None:
        self.fast_window = fast_window
        self.slow_window = slow_window
        self.support_tolerance_pct = support_tolerance_pct
        self.atr_multiplier = atr_multiplier
        self.target_r_multiple = target_r_multiple

    def generate(self, symbol: str, bars: pd.DataFrame) -> Signal | None:
        if len(bars) < self.slow_window + 2:
            return None
        sma_fast = sma(bars["close"], self.fast_window)
        sma_slow = sma(bars["close"], self.slow_window)
        last = bars.iloc[-1]
        fast_val, slow_val = sma_fast.iloc[-1], sma_slow.iloc[-1]
        if pd.isna(fast_val) or pd.isna(slow_val) or fast_val <= 0:
            return None
        uptrend = last["close"] > slow_val
        near_support = abs(last["low"] - fast_val) / fast_val < self.support_tolerance_pct
        bounced = last["close"] > last["open"] and last["close"] > fast_val
        if not (uptrend and near_support and bounced):
            return None
        atr_val = atr(bars).iloc[-1]
        if pd.isna(atr_val) or atr_val <= 0:
            return None
        entry = float(last["close"])
        stop = min(atr_stop_price(entry, float(atr_val), self.atr_multiplier, "long"), float(last["low"]) - 0.01)
        if stop >= entry:
            return None
        target = entry + (entry - stop) * self.target_r_multiple
        score = float((last["close"] - fast_val) / atr_val)
        return Signal(
            symbol=symbol,
            strategy=self.name,
            direction="long",
            score=score,
            entry_price=entry,
            stop_price=stop,
            target_price=target,
            reason=f"pullback to {self.fast_window}d SMA in an uptrend, bounced",
        )

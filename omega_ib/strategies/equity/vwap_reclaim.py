"""Long when intraday price dips below VWAP and reclaims it on the latest bar."""

from __future__ import annotations

import pandas as pd

from omega_ib.risk.guard import atr_stop_price
from omega_ib.strategies.equity.base import Signal, Strategy
from omega_ib.strategies.equity.indicators import atr, vwap


class VWAPReclaim(Strategy):
    name = "vwap_reclaim"

    def __init__(self, atr_multiplier: float = 1.5, target_r_multiple: float = 2.0) -> None:
        self.atr_multiplier = atr_multiplier
        self.target_r_multiple = target_r_multiple

    def generate(self, symbol: str, bars: pd.DataFrame) -> Signal | None:
        if len(bars) < 16:
            return None
        vw = vwap(bars)
        last = bars.iloc[-1]
        prev = bars.iloc[-2]
        if pd.isna(vw.iloc[-1]) or pd.isna(vw.iloc[-2]):
            return None
        was_below = prev["close"] < vw.iloc[-2]
        now_above = last["close"] > vw.iloc[-1]
        if not (was_below and now_above):
            return None
        atr_val = atr(bars).iloc[-1]
        if pd.isna(atr_val) or atr_val <= 0:
            return None
        entry = float(last["close"])
        stop = min(float(last["low"]), atr_stop_price(entry, float(atr_val), self.atr_multiplier, "long"))
        if stop >= entry:
            return None
        target = entry + (entry - stop) * self.target_r_multiple
        score = float((entry - vw.iloc[-1]) / atr_val)
        return Signal(
            symbol=symbol,
            strategy=self.name,
            direction="long",
            score=score,
            entry_price=entry,
            stop_price=stop,
            target_price=target,
            reason="reclaimed VWAP after dipping below it",
        )

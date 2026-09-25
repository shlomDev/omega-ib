"""Long on a morning gap-up that holds (closes above its own open), aka gap-and-go."""

from __future__ import annotations

import pandas as pd

from omega_ib.risk.guard import atr_stop_price
from omega_ib.strategies.equity.base import Signal, Strategy
from omega_ib.strategies.equity.indicators import atr


class GapAndGo(Strategy):
    name = "gap_and_go"

    def __init__(self, min_gap_pct: float = 0.02, atr_multiplier: float = 1.5, target_r_multiple: float = 2.0) -> None:
        self.min_gap_pct = min_gap_pct
        self.atr_multiplier = atr_multiplier
        self.target_r_multiple = target_r_multiple

    def generate(self, symbol: str, bars: pd.DataFrame) -> Signal | None:
        if len(bars) < 16:
            return None
        yesterday = bars.iloc[-2]
        today = bars.iloc[-1]
        if yesterday["close"] <= 0:
            return None
        gap_pct = (today["open"] - yesterday["close"]) / yesterday["close"]
        if gap_pct < self.min_gap_pct:
            return None
        if today["close"] < today["open"]:  # gap faded intraday, didn't hold
            return None
        atr_val = atr(bars.iloc[:-1]).iloc[-1]  # ATR through yesterday, entry is today's close
        if pd.isna(atr_val) or atr_val <= 0:
            return None
        entry = float(today["close"])
        stop = min(float(today["open"]), atr_stop_price(entry, float(atr_val), self.atr_multiplier, "long"))
        if stop >= entry:
            return None
        target = entry + (entry - stop) * self.target_r_multiple
        score = float(gap_pct / (atr_val / yesterday["close"]))
        return Signal(
            symbol=symbol,
            strategy=self.name,
            direction="long",
            score=score,
            entry_price=entry,
            stop_price=stop,
            target_price=target,
            reason=f"gap up {gap_pct:.1%} held above open",
        )

"""Pluggable strategy interface for the equity autopilot.

Each strategy consumes an OHLCV bar DataFrame for one symbol and emits at most
one Signal. Strategies never touch the broker or risk/guard.py directly --
signals flow into sizing (risk/guard.py's fixed_fractional_size) and
execution/engine.py, the only caller of RiskGuard.place_order for equities.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

import pandas as pd


@dataclass
class Signal:
    symbol: str
    strategy: str
    direction: str  # "long" / "short"
    score: float  # ranking strength, higher = more attractive; comparable within a strategy
    entry_price: float
    stop_price: float
    target_price: float
    reason: str = ""


class Strategy(ABC):
    name: str = "base"

    @abstractmethod
    def generate(self, symbol: str, bars: pd.DataFrame) -> Signal | None:
        """bars: OHLCV DataFrame indexed by date/time, ascending. None if no setup."""
        ...


def run_strategies(strategies: list[Strategy], symbol: str, bars: pd.DataFrame) -> list[Signal]:
    signals = []
    for strategy in strategies:
        signal = strategy.generate(symbol, bars)
        if signal is not None:
            signals.append(signal)
    return signals


def rank_signals(signals: list[Signal]) -> list[Signal]:
    """Highest score first. Ties broken by symbol for determinism."""
    return sorted(signals, key=lambda s: (-s.score, s.symbol))

"""Pluggable options strategy interface.

Each strategy inspects an OptionChain and proposes at most one OptionStructure
(legs only -- no order/broker plumbing). options_builder.py scores candidates
and converts the winner into a BAG Contract + OrderRequest for
execution/engine.py, which places it through risk/guard.py exactly like every
other order.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from omega_ib.data.options import OptionChain, OptionQuote, is_liquid


@dataclass
class OptionLeg:
    quote: OptionQuote
    action: str  # BUY / SELL
    ratio: int = 1


@dataclass
class OptionStructure:
    symbol: str
    strategy: str
    legs: list[OptionLeg]
    expiry: str
    reason: str = ""


class OptionsStrategy(ABC):
    name: str = "base"

    @abstractmethod
    def generate(self, chain: OptionChain, expiry: str) -> OptionStructure | None:
        """chain: full chain for the underlying. expiry: the (near-term) expiry to
        build around -- calendar spreads use the next available expiry after this
        one for their long leg. None if no valid structure can be built (e.g. no
        liquid quote near the target delta)."""
        ...


def nearest_by_delta(
    quotes: list[OptionQuote],
    target_delta: float,
    max_spread_pct: float = 0.10,
    min_open_interest: int = 50,
    max_delta_distance: float = 0.15,
) -> OptionQuote | None:
    """Liquid quote whose delta is closest to target_delta, or None if nothing
    liquid is within max_delta_distance of the target."""
    candidates = [q for q in quotes if is_liquid(q, max_spread_pct, min_open_interest)]
    if not candidates:
        return None
    best = min(candidates, key=lambda q: abs(q.delta - target_delta))
    if abs(best.delta - target_delta) > max_delta_distance:
        return None
    return best

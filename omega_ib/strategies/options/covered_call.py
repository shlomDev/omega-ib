"""Covered call: sell one call near a target delta against 100 shares held.

This strategy only proposes the call leg -- risk/guard.py's naked-short-call
check independently verifies enough underlying shares are held before letting
the order through, so this module never has to duplicate that check.
"""

from __future__ import annotations

from omega_ib.data.options import OptionChain
from omega_ib.strategies.options.base import OptionLeg, OptionsStrategy, OptionStructure, nearest_by_delta


class CoveredCall(OptionsStrategy):
    name = "covered_call"

    def __init__(self, target_delta: float = 0.30, max_spread_pct: float = 0.10, min_open_interest: int = 50) -> None:
        self.target_delta = target_delta
        self.max_spread_pct = max_spread_pct
        self.min_open_interest = min_open_interest

    def generate(self, chain: OptionChain, expiry: str) -> OptionStructure | None:
        calls = [q for q in chain.by_expiry(expiry) if q.right == "C"]
        short_call = nearest_by_delta(calls, self.target_delta, self.max_spread_pct, self.min_open_interest)
        if short_call is None:
            return None
        leg = OptionLeg(quote=short_call, action="SELL", ratio=1)
        return OptionStructure(
            symbol=chain.symbol,
            strategy=self.name,
            legs=[leg],
            expiry=expiry,
            reason=f"sell {short_call.strike}C at delta {short_call.delta:.2f} against held shares",
        )

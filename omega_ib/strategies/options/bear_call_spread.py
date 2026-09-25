"""Bear call spread (short call vertical): sell a call near target delta, buy a
further-OTM call as protection. Defined-risk bearish/neutral credit spread --
the long call caps the loss, so this never trips the naked-short-call guard
check (which requires SELL C legs to be matched by BUY C legs in a BAG)."""

from __future__ import annotations

from omega_ib.data.options import OptionChain, is_liquid
from omega_ib.strategies.options.base import OptionLeg, OptionsStrategy, OptionStructure, nearest_by_delta


class BearCallSpread(OptionsStrategy):
    name = "bear_call_spread"

    def __init__(
        self,
        short_delta: float = 0.30,
        wing_width: float = 5.0,
        max_spread_pct: float = 0.10,
        min_open_interest: int = 50,
    ) -> None:
        self.short_delta = short_delta
        self.wing_width = wing_width
        self.max_spread_pct = max_spread_pct
        self.min_open_interest = min_open_interest

    def generate(self, chain: OptionChain, expiry: str) -> OptionStructure | None:
        calls = [q for q in chain.by_expiry(expiry) if q.right == "C"]
        short_call = nearest_by_delta(calls, self.short_delta, self.max_spread_pct, self.min_open_interest)
        if short_call is None:
            return None
        long_strike = short_call.strike + self.wing_width
        long_call = chain.find(expiry, long_strike, "C")
        if long_call is None or not is_liquid(long_call, self.max_spread_pct, self.min_open_interest):
            return None
        legs = [OptionLeg(short_call, "SELL"), OptionLeg(long_call, "BUY")]
        return OptionStructure(
            symbol=chain.symbol,
            strategy=self.name,
            legs=legs,
            expiry=expiry,
            reason=f"sell {short_call.strike}C / buy {long_call.strike}C",
        )

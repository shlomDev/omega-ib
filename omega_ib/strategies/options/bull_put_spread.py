"""Bull put spread (short put vertical): sell a put near target delta, buy a
further-OTM put as protection. Defined-risk bullish/neutral credit spread."""

from __future__ import annotations

from omega_ib.data.options import OptionChain, is_liquid
from omega_ib.strategies.options.base import OptionLeg, OptionsStrategy, OptionStructure, nearest_by_delta


class BullPutSpread(OptionsStrategy):
    name = "bull_put_spread"

    def __init__(
        self,
        short_delta: float = -0.30,
        wing_width: float = 5.0,
        max_spread_pct: float = 0.10,
        min_open_interest: int = 50,
    ) -> None:
        self.short_delta = short_delta
        self.wing_width = wing_width
        self.max_spread_pct = max_spread_pct
        self.min_open_interest = min_open_interest

    def generate(self, chain: OptionChain, expiry: str) -> OptionStructure | None:
        puts = [q for q in chain.by_expiry(expiry) if q.right == "P"]
        short_put = nearest_by_delta(puts, self.short_delta, self.max_spread_pct, self.min_open_interest)
        if short_put is None:
            return None
        long_strike = short_put.strike - self.wing_width
        long_put = chain.find(expiry, long_strike, "P")
        if long_put is None or not is_liquid(long_put, self.max_spread_pct, self.min_open_interest):
            return None
        legs = [OptionLeg(short_put, "SELL"), OptionLeg(long_put, "BUY")]
        return OptionStructure(
            symbol=chain.symbol,
            strategy=self.name,
            legs=legs,
            expiry=expiry,
            reason=f"sell {short_put.strike}P / buy {long_put.strike}P",
        )

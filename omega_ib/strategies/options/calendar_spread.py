"""Calendar (time) spread: sell a near-term option, buy the same strike/right in
the next available expiry. Profits from time decay differential and/or a rise
in near-term IV relative to the back month."""

from __future__ import annotations

from omega_ib.data.options import OptionChain, is_liquid
from omega_ib.strategies.options.base import OptionLeg, OptionsStrategy, OptionStructure, nearest_by_delta


class CalendarSpread(OptionsStrategy):
    name = "calendar_spread"

    def __init__(
        self,
        target_delta: float = 0.50,
        right: str = "C",
        max_spread_pct: float = 0.10,
        min_open_interest: int = 50,
    ) -> None:
        self.target_delta = target_delta
        self.right = right
        self.max_spread_pct = max_spread_pct
        self.min_open_interest = min_open_interest

    def generate(self, chain: OptionChain, expiry: str) -> OptionStructure | None:
        expiries = chain.expiries()
        if expiry not in expiries:
            return None
        idx = expiries.index(expiry)
        if idx + 1 >= len(expiries):
            return None  # no further-out expiry available to buy
        long_expiry = expiries[idx + 1]
        near_options = [q for q in chain.by_expiry(expiry) if q.right == self.right]
        short_leg = nearest_by_delta(near_options, self.target_delta, self.max_spread_pct, self.min_open_interest)
        if short_leg is None:
            return None
        long_quote = chain.find(long_expiry, short_leg.strike, self.right)
        if long_quote is None or not is_liquid(long_quote, self.max_spread_pct, self.min_open_interest):
            return None
        legs = [OptionLeg(short_leg, "SELL"), OptionLeg(long_quote, "BUY")]
        return OptionStructure(
            symbol=chain.symbol,
            strategy=self.name,
            legs=legs,
            expiry=expiry,
            reason=f"sell {expiry} {short_leg.strike}{self.right} / buy {long_expiry} {short_leg.strike}{self.right}",
        )

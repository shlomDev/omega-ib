"""Long call/put debit spreads: buy a near-the-money option, sell a further-OTM
option in the same expiry to reduce cost (and cap upside). Directional bets
with defined risk equal to the net debit paid."""

from __future__ import annotations

from omega_ib.data.options import OptionChain, is_liquid
from omega_ib.strategies.options.base import OptionLeg, OptionsStrategy, OptionStructure, nearest_by_delta


class LongCallDebitSpread(OptionsStrategy):
    name = "long_call_debit_spread"

    def __init__(
        self,
        long_delta: float = 0.60,
        wing_width: float = 5.0,
        max_spread_pct: float = 0.10,
        min_open_interest: int = 50,
    ) -> None:
        self.long_delta = long_delta
        self.wing_width = wing_width
        self.max_spread_pct = max_spread_pct
        self.min_open_interest = min_open_interest

    def generate(self, chain: OptionChain, expiry: str) -> OptionStructure | None:
        calls = [q for q in chain.by_expiry(expiry) if q.right == "C"]
        long_call = nearest_by_delta(calls, self.long_delta, self.max_spread_pct, self.min_open_interest)
        if long_call is None:
            return None
        short_strike = long_call.strike + self.wing_width
        short_call = chain.find(expiry, short_strike, "C")
        if short_call is None or not is_liquid(short_call, self.max_spread_pct, self.min_open_interest):
            return None
        legs = [OptionLeg(long_call, "BUY"), OptionLeg(short_call, "SELL")]
        return OptionStructure(
            symbol=chain.symbol,
            strategy=self.name,
            legs=legs,
            expiry=expiry,
            reason=f"buy {long_call.strike}C / sell {short_call.strike}C",
        )


class LongPutDebitSpread(OptionsStrategy):
    name = "long_put_debit_spread"

    def __init__(
        self,
        long_delta: float = -0.60,
        wing_width: float = 5.0,
        max_spread_pct: float = 0.10,
        min_open_interest: int = 50,
    ) -> None:
        self.long_delta = long_delta
        self.wing_width = wing_width
        self.max_spread_pct = max_spread_pct
        self.min_open_interest = min_open_interest

    def generate(self, chain: OptionChain, expiry: str) -> OptionStructure | None:
        puts = [q for q in chain.by_expiry(expiry) if q.right == "P"]
        long_put = nearest_by_delta(puts, self.long_delta, self.max_spread_pct, self.min_open_interest)
        if long_put is None:
            return None
        short_strike = long_put.strike - self.wing_width
        short_put = chain.find(expiry, short_strike, "P")
        if short_put is None or not is_liquid(short_put, self.max_spread_pct, self.min_open_interest):
            return None
        legs = [OptionLeg(long_put, "BUY"), OptionLeg(short_put, "SELL")]
        return OptionStructure(
            symbol=chain.symbol,
            strategy=self.name,
            legs=legs,
            expiry=expiry,
            reason=f"buy {long_put.strike}P / sell {short_put.strike}P",
        )

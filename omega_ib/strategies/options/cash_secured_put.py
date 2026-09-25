"""Cash-secured put: sell one put near a target delta, collateralized by cash.

Bullish/neutral income strategy. Max loss is defined (strike - premium) *
100, so it never trips the naked-short-call guard check (that only applies to
calls) and is fine for a cash account.
"""

from __future__ import annotations

from omega_ib.data.options import OptionChain
from omega_ib.strategies.options.base import OptionLeg, OptionsStrategy, OptionStructure, nearest_by_delta


class CashSecuredPut(OptionsStrategy):
    name = "cash_secured_put"

    def __init__(self, target_delta: float = -0.30, max_spread_pct: float = 0.10, min_open_interest: int = 50) -> None:
        self.target_delta = target_delta
        self.max_spread_pct = max_spread_pct
        self.min_open_interest = min_open_interest

    def generate(self, chain: OptionChain, expiry: str) -> OptionStructure | None:
        puts = [q for q in chain.by_expiry(expiry) if q.right == "P"]
        short_put = nearest_by_delta(puts, self.target_delta, self.max_spread_pct, self.min_open_interest)
        if short_put is None:
            return None
        leg = OptionLeg(quote=short_put, action="SELL", ratio=1)
        return OptionStructure(
            symbol=chain.symbol,
            strategy=self.name,
            legs=[leg],
            expiry=expiry,
            reason=f"sell {short_put.strike}P at delta {short_put.delta:.2f}",
        )

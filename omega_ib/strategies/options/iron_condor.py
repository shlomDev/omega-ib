"""Iron condor: a bull put spread plus a bear call spread, same expiry. Defined-risk,
neutral income strategy that profits if the underlying stays between the short strikes."""

from __future__ import annotations

from omega_ib.data.options import OptionChain
from omega_ib.strategies.options.base import OptionsStrategy, OptionStructure
from omega_ib.strategies.options.bear_call_spread import BearCallSpread
from omega_ib.strategies.options.bull_put_spread import BullPutSpread


class IronCondor(OptionsStrategy):
    name = "iron_condor"

    def __init__(
        self,
        short_delta: float = 0.30,
        wing_width: float = 5.0,
        max_spread_pct: float = 0.10,
        min_open_interest: int = 50,
    ) -> None:
        self._put_side = BullPutSpread(-short_delta, wing_width, max_spread_pct, min_open_interest)
        self._call_side = BearCallSpread(short_delta, wing_width, max_spread_pct, min_open_interest)

    def generate(self, chain: OptionChain, expiry: str) -> OptionStructure | None:
        put_spread = self._put_side.generate(chain, expiry)
        call_spread = self._call_side.generate(chain, expiry)
        if put_spread is None or call_spread is None:
            return None
        legs = put_spread.legs + call_spread.legs
        return OptionStructure(
            symbol=chain.symbol,
            strategy=self.name,
            legs=legs,
            expiry=expiry,
            reason=f"{put_spread.reason} + {call_spread.reason}",
        )

"""Shared synthetic option chain builder for strategies/options and options_builder tests.

Not a test module itself (no test_ prefix) -- imported by the real test files.
"""

from __future__ import annotations

from omega_ib.data.options import OptionChain, OptionQuote

STRIKES = [80, 85, 90, 95, 100, 105, 110, 115, 120]
CALL_DELTAS = [0.95, 0.90, 0.80, 0.65, 0.50, 0.35, 0.20, 0.10, 0.05]
PUT_DELTAS = [-0.05, -0.10, -0.20, -0.35, -0.50, -0.65, -0.80, -0.90, -0.95]
NEAR_EXPIRY = "20261218"
FAR_EXPIRY = "20270115"


def build_chain(symbol: str = "AAPL", underlying_price: float = 100.0, expiries: tuple[str, ...] = (NEAR_EXPIRY, FAR_EXPIRY)) -> OptionChain:
    quotes: list[OptionQuote] = []
    for expiry_idx, expiry in enumerate(expiries):
        premium_bump = expiry_idx * 0.5  # further-dated options cost a bit more
        for strike, call_delta, put_delta in zip(STRIKES, CALL_DELTAS, PUT_DELTAS, strict=True):
            call_mid = max(1.0, (underlying_price - strike) * 0.5 + 5.0) + premium_bump
            put_mid = max(1.0, (strike - underlying_price) * 0.5 + 5.0) + premium_bump
            quotes.append(
                OptionQuote(
                    symbol=symbol, expiry=expiry, strike=float(strike), right="C",
                    bid=call_mid - 0.02, ask=call_mid + 0.02, open_interest=500,
                    delta=call_delta, gamma=0.02, theta=-0.03, vega=0.10,
                )
            )
            quotes.append(
                OptionQuote(
                    symbol=symbol, expiry=expiry, strike=float(strike), right="P",
                    bid=put_mid - 0.02, ask=put_mid + 0.02, open_interest=500,
                    delta=put_delta, gamma=0.02, theta=-0.03, vega=0.10,
                )
            )
    return OptionChain(symbol=symbol, underlying_price=underlying_price, quotes=quotes)

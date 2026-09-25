"""Options chains, greeks, IV rank/percentile, liquidity filters.

No IB Gateway is reachable in this sandbox: FakeOptionsData is an in-memory
provider used by strategies/options/* and options_builder.py tests. IBOptionsData
wraps ib_async's reqSecDefOptParams/reqTickers/modelGreeks for the real chain;
it is not exercised end-to-end here (see PROGRESS.md).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class OptionQuote:
    symbol: str
    expiry: str  # YYYYMMDD
    strike: float
    right: str  # "C" / "P"
    bid: float
    ask: float
    last: float = 0.0
    volume: int = 0
    open_interest: int = 0
    iv: float = 0.0
    delta: float = 0.0
    gamma: float = 0.0
    theta: float = 0.0
    vega: float = 0.0

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2

    @property
    def spread_pct(self) -> float:
        """Bid-ask spread as a fraction of mid price. inf if mid is 0 (unquoted)."""
        if self.mid <= 0:
            return float("inf")
        return (self.ask - self.bid) / self.mid


def is_liquid(quote: OptionQuote, max_spread_pct: float = 0.10, min_open_interest: int = 100) -> bool:
    return quote.spread_pct <= max_spread_pct and quote.open_interest >= min_open_interest


@dataclass
class OptionChain:
    symbol: str
    underlying_price: float
    quotes: list[OptionQuote]

    def expiries(self) -> list[str]:
        return sorted({q.expiry for q in self.quotes})

    def by_expiry(self, expiry: str) -> list[OptionQuote]:
        return [q for q in self.quotes if q.expiry == expiry]

    def find(self, expiry: str, strike: float, right: str) -> OptionQuote | None:
        for q in self.quotes:
            if q.expiry == expiry and q.strike == strike and q.right == right:
                return q
        return None

    def liquid_quotes(self, max_spread_pct: float = 0.10, min_open_interest: int = 100) -> list[OptionQuote]:
        return [q for q in self.quotes if is_liquid(q, max_spread_pct, min_open_interest)]


def iv_rank(current_iv: float, iv_history: list[float]) -> float:
    """IV Rank: where current IV sits between the historical min and max, 0-100."""
    if not iv_history:
        return 0.0
    lo, hi = min(iv_history), max(iv_history)
    if hi <= lo:
        return 0.0
    return max(0.0, min(100.0, (current_iv - lo) / (hi - lo) * 100))


def iv_percentile(current_iv: float, iv_history: list[float]) -> float:
    """IV Percentile: % of days in the sample with IV strictly below current_iv, 0-100."""
    if not iv_history:
        return 0.0
    below = sum(1 for iv in iv_history if iv < current_iv)
    return below / len(iv_history) * 100


class OptionsDataProvider(ABC):
    @abstractmethod
    def get_chain(self, symbol: str, expiry: str | None = None) -> OptionChain: ...

    @abstractmethod
    def iv_history(self, symbol: str, lookback_days: int = 252) -> list[float]: ...


class FakeOptionsData(OptionsDataProvider):
    """In-memory chains/IV history, settable by tests and dry-run."""

    def __init__(self) -> None:
        self.chains: dict[str, OptionChain] = {}
        self.iv_histories: dict[str, list[float]] = {}

    def set_chain(self, symbol: str, chain: OptionChain) -> None:
        self.chains[symbol] = chain

    def get_chain(self, symbol: str, expiry: str | None = None) -> OptionChain:
        chain = self.chains.get(symbol)
        if chain is None:
            return OptionChain(symbol=symbol, underlying_price=0.0, quotes=[])
        if expiry is None:
            return chain
        return OptionChain(symbol=symbol, underlying_price=chain.underlying_price, quotes=chain.by_expiry(expiry))

    def set_iv_history(self, symbol: str, history: list[float]) -> None:
        self.iv_histories[symbol] = history

    def iv_history(self, symbol: str, lookback_days: int = 252) -> list[float]:
        return self.iv_histories.get(symbol, [])[-lookback_days:]


class IBOptionsData(OptionsDataProvider):
    """Wraps ib_async's option-chain/greeks calls. No IV history feed is wired up
    (would need a paid data subscription); iv_history returns [] until one exists."""

    def __init__(self, ib_broker) -> None:
        self._ib = ib_broker.ib

    def get_chain(self, symbol: str, expiry: str | None = None) -> OptionChain:
        from ib_async.contract import Option, Stock

        underlying = Stock(symbol, "SMART", "USD")
        [qualified] = self._ib.qualifyContracts(underlying)
        [ticker] = self._ib.reqTickers(qualified)
        underlying_price = ticker.marketPrice()
        params = self._ib.reqSecDefOptParams(qualified.symbol, "", qualified.secType, qualified.conId)
        quotes: list[OptionQuote] = []
        for p in params:
            expiries = [expiry] if expiry else sorted(p.expirations)
            for exp in expiries:
                for strike in sorted(p.strikes):
                    for right in ("C", "P"):
                        contract = Option(symbol, exp, strike, right, "SMART", currency="USD")
                        opt_ticker = self._ib.reqTickers(contract)[0]
                        greeks = opt_ticker.modelGreeks
                        quotes.append(
                            OptionQuote(
                                symbol=symbol,
                                expiry=exp,
                                strike=strike,
                                right=right,
                                bid=opt_ticker.bid or 0.0,
                                ask=opt_ticker.ask or 0.0,
                                last=opt_ticker.last or 0.0,
                                volume=int(opt_ticker.volume or 0),
                                iv=greeks.impliedVol if greeks else 0.0,
                                delta=greeks.delta if greeks else 0.0,
                                gamma=greeks.gamma if greeks else 0.0,
                                theta=greeks.theta if greeks else 0.0,
                                vega=greeks.vega if greeks else 0.0,
                            )
                        )
        return OptionChain(symbol=symbol, underlying_price=underlying_price, quotes=quotes)

    def iv_history(self, symbol: str, lookback_days: int = 252) -> list[float]:
        return []

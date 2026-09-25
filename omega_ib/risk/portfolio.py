"""Portfolio-level risk aggregation: greeks, beta-weighted delta, sector concentration, VaR.

This is read-only reporting (feature C in CLAUDE.md) -- it never touches the
broker's order-placement path (that's risk/guard.py). Options greeks are optional
fields on PositionRisk; until data/options.py (phase 6) exists, callers building
equity-only portfolios simply omit them and every options-specific total is zero.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PositionRisk:
    """One position's contribution to portfolio risk.

    `delta_shares` is delta already expressed in underlying-share terms, i.e.
    quantity for a stock, or delta * quantity * contract_multiplier for an option.
    Dollar greeks (gamma/theta/vega) are per the whole position, not per share/contract.
    """

    symbol: str
    sec_type: str
    quantity: float
    price: float
    market_value: float
    delta_shares: float = 0.0
    gamma: float = 0.0
    theta: float = 0.0
    vega: float = 0.0
    beta: float = 1.0
    sector: str = "Unknown"


@dataclass
class PortfolioGreeks:
    total_delta_shares: float = 0.0
    total_gamma: float = 0.0
    total_theta: float = 0.0
    total_vega: float = 0.0


def aggregate_greeks(positions: list[PositionRisk]) -> PortfolioGreeks:
    return PortfolioGreeks(
        total_delta_shares=sum(p.delta_shares for p in positions),
        total_gamma=sum(p.gamma for p in positions),
        total_theta=sum(p.theta for p in positions),
        total_vega=sum(p.vega for p in positions),
    )


def beta_weighted_delta_vs_spy(positions: list[PositionRisk], spy_price: float) -> float:
    """Portfolio delta expressed in SPY-equivalent shares, weighting each position by its beta."""
    if spy_price <= 0:
        return 0.0
    dollar_delta = sum(p.delta_shares * p.price * p.beta for p in positions)
    return dollar_delta / spy_price


@dataclass
class SectorExposure:
    sector: str
    market_value: float
    pct_of_nav: float


def sector_concentration(positions: list[PositionRisk], nav: float) -> list[SectorExposure]:
    """Exposure grouped by sector, sorted largest first. Empty if nav <= 0."""
    if nav <= 0:
        return []
    totals: dict[str, float] = {}
    for p in positions:
        totals[p.sector] = totals.get(p.sector, 0.0) + p.market_value
    exposures = [
        SectorExposure(sector=sector, market_value=value, pct_of_nav=value / nav)
        for sector, value in totals.items()
    ]
    return sorted(exposures, key=lambda e: abs(e.market_value), reverse=True)


def underlying_concentration(positions: list[PositionRisk], nav: float) -> list[SectorExposure]:
    """Same shape as sector_concentration but grouped by underlying symbol."""
    if nav <= 0:
        return []
    totals: dict[str, float] = {}
    for p in positions:
        totals[p.symbol] = totals.get(p.symbol, 0.0) + p.market_value
    exposures = [
        SectorExposure(sector=symbol, market_value=value, pct_of_nav=value / nav)
        for symbol, value in totals.items()
    ]
    return sorted(exposures, key=lambda e: abs(e.market_value), reverse=True)


def historical_var(daily_returns: list[float], confidence: float = 0.95) -> float:
    """Historical VaR as a return (typically negative) at the given confidence level.

    E.g. historical_var(returns, 0.95) == -0.03 means: on the worst 5% of days in
    the sample, the portfolio lost 3% or more. Multiply by NAV for a dollar VaR.
    """
    if not daily_returns:
        return 0.0
    sorted_returns = sorted(daily_returns)
    idx = int(round((1 - confidence) * len(sorted_returns)))
    idx = min(max(idx, 0), len(sorted_returns) - 1)
    return sorted_returns[idx]


@dataclass
class RiskLimitGauge:
    """Distance-to-cap reporting for a single hard limit, for the risk-limit gauges in the UI."""

    name: str
    current: float
    limit: float
    breached: bool = field(init=False)

    def __post_init__(self) -> None:
        self.breached = self.current >= self.limit

    @property
    def room_remaining(self) -> float:
        return self.limit - self.current


def daily_loss_gauge(day_pnl_pct: float, max_daily_loss_pct_nav: float) -> RiskLimitGauge:
    """day_pnl_pct is negative when losing; current is expressed as a positive loss magnitude."""
    return RiskLimitGauge(name="daily_loss_pct_nav", current=max(0.0, -day_pnl_pct), limit=max_daily_loss_pct_nav)


def open_positions_gauge(open_positions: int, max_open_positions: int) -> RiskLimitGauge:
    return RiskLimitGauge(name="open_positions", current=float(open_positions), limit=float(max_open_positions))

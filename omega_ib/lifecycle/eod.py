"""End-of-day lifecycle rules for equity positions: flatten leveraged ETFs,
earnings-proximity exits, overnight-hold criteria.

Options 21-DTE / 50%-profit management is added in lifecycle alongside
options_builder.py once phase 6 (data/options.py) exists -- this module covers
the equity side only for now. These functions decide *whether* a position
should be closed; the caller is responsible for routing the resulting exit
order through risk/guard.py, exactly like every other order.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from omega_ib.data.market import StaticEarningsCalendar


@dataclass
class EODDecision:
    symbol: str
    action: str  # "flatten" / "hold"
    reason: str


LEVERAGED_ETF_KEYWORDS = frozenset(
    {
        "TQQQ", "SQQQ", "UPRO", "SPXU", "SPXL", "SPXS", "SOXL", "SOXS",
        "TNA", "TZA", "UDOW", "SDOW", "LABU", "LABD", "FAS", "FAZ",
    }
)


def is_leveraged_etf(symbol: str, leveraged_symbols: frozenset[str] = LEVERAGED_ETF_KEYWORDS) -> bool:
    return symbol.upper() in leveraged_symbols


def leveraged_etf_flatten_decision(symbol: str, leveraged_symbols: frozenset[str] = LEVERAGED_ETF_KEYWORDS) -> EODDecision | None:
    """Leveraged/inverse ETFs are never held overnight -- decay risk compounds daily."""
    if is_leveraged_etf(symbol, leveraged_symbols):
        return EODDecision(symbol=symbol, action="flatten", reason="leveraged/inverse ETF: never held overnight")
    return None


def earnings_proximity_decision(
    symbol: str,
    as_of: dt.date,
    earnings_calendar: StaticEarningsCalendar,
    min_days_buffer: int = 1,
) -> EODDecision | None:
    """Flatten ahead of an earnings print within `min_days_buffer` days to avoid gap risk."""
    days = earnings_calendar.days_until_earnings(symbol, as_of)
    if days is not None and 0 <= days <= min_days_buffer:
        return EODDecision(symbol=symbol, action="flatten", reason=f"earnings in {days} day(s): avoiding gap risk")
    return None


def overnight_hold_decision(
    symbol: str,
    unrealized_pnl_pct: float,
    stop_loss_pct: float,
    entered_today: bool,
    max_loss_hold_pct: float = -0.03,
) -> EODDecision | None:
    """Flatten a same-day entry that's already beyond a max intraday loss threshold
    rather than risk it gapping further against the stop overnight."""
    if entered_today and unrealized_pnl_pct <= max_loss_hold_pct:
        return EODDecision(
            symbol=symbol,
            action="flatten",
            reason=f"same-day entry down {unrealized_pnl_pct:.1%}, beyond overnight-hold threshold",
        )
    return None


def eod_decisions_for_position(
    symbol: str,
    as_of: dt.date,
    earnings_calendar: StaticEarningsCalendar,
    unrealized_pnl_pct: float = 0.0,
    stop_loss_pct: float = 0.0,
    entered_today: bool = False,
    leveraged_symbols: frozenset[str] = LEVERAGED_ETF_KEYWORDS,
) -> EODDecision:
    """Runs every EOD rule for one position and returns the first flatten reason found,
    or a "hold" decision if nothing applies."""
    checks = (
        lambda: leveraged_etf_flatten_decision(symbol, leveraged_symbols),
        lambda: earnings_proximity_decision(symbol, as_of, earnings_calendar),
        lambda: overnight_hold_decision(symbol, unrealized_pnl_pct, stop_loss_pct, entered_today),
    )
    for check in checks:
        decision = check()
        if decision is not None:
            return decision
    return EODDecision(symbol=symbol, action="hold", reason="no EOD rule triggered")

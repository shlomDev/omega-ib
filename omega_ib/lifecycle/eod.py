"""End-of-day lifecycle rules: equity (flatten leveraged ETFs, earnings-proximity
exits, overnight-hold criteria) and options position management (take profit at
50% of max credit, roll/exit at 21 DTE, stop out at 2x credit received).

These functions decide *whether* a position should be closed/rolled; the caller
is responsible for routing the resulting exit order through risk/guard.py,
exactly like every other order.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from omega_ib.data.market import StaticEarningsCalendar


@dataclass
class EODDecision:
    symbol: str
    action: str  # "flatten" / "roll" / "hold"
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


def days_to_expiration(expiry: str, as_of: dt.date) -> int:
    """expiry: YYYYMMDD (IB's expiry format, as used by data/options.OptionQuote)."""
    expiry_date = dt.datetime.strptime(expiry, "%Y%m%d").date()
    return (expiry_date - as_of).days


def options_management_decision(
    symbol: str,
    expiry: str,
    as_of: dt.date,
    entry_net_price: float,
    current_net_price: float,
    profit_target_pct: float = 0.50,
    roll_dte_threshold: int = 21,
    stop_loss_multiple: float = 2.0,
) -> EODDecision:
    """CLAUDE.md feature B management rules: take profit at 50%, exit/roll at 21
    DTE, stop at 2x credit. Both `entry_net_price` and `current_net_price` use
    options_builder.net_price's sign convention (negative = credit received,
    positive = debit paid) for the position as a whole, so this function works
    for both credit and debit structures without the caller needing to know which.
    """
    days_left = days_to_expiration(expiry, as_of)
    if entry_net_price < 0:  # net credit received: profit as current_net_price falls toward 0
        credit = -entry_net_price
        cost_to_close = current_net_price  # positive = paying a debit to close
        profit_pct = (credit - cost_to_close) / credit if credit else 0.0
        if profit_pct >= profit_target_pct:
            return EODDecision(symbol=symbol, action="flatten", reason=f"take profit: {profit_pct:.0%} of max credit captured")
        if cost_to_close >= credit * stop_loss_multiple:
            return EODDecision(symbol=symbol, action="flatten", reason=f"stop loss: cost to close is {stop_loss_multiple:.0f}x initial credit")
    elif entry_net_price > 0:  # net debit paid: profit as current_net_price rises above entry.
        # CLAUDE.md's "stop at 2x credit" rule is credit-specific; debit structures
        # only get the take-profit and DTE-roll rules here.
        debit = entry_net_price
        value_now = -current_net_price  # what we'd receive selling to close
        profit_pct = (value_now - debit) / debit if debit else 0.0
        if profit_pct >= profit_target_pct:
            return EODDecision(symbol=symbol, action="flatten", reason=f"take profit: {profit_pct:.0%} gain on debit paid")
    if days_left <= roll_dte_threshold:
        return EODDecision(symbol=symbol, action="roll", reason=f"{days_left} DTE at or below the {roll_dte_threshold}-day roll threshold")
    return EODDecision(symbol=symbol, action="hold", reason="no options management rule triggered")

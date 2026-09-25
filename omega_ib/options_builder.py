"""Combo (BAG) order construction + P/L math for options structures.

Turns an OptionStructure (from strategies/options/*.py) into:
  - a Contract(sec_type="BAG") + OrderRequest ready for execution/engine.py
  - max profit/loss, breakeven(s), a rough POP (probability of profit), expected
    value, net greeks, and payoff-curve data points for the UI chart.

No option-pricing model (e.g. Black-Scholes) is implemented here: POP is
approximated from the short/long legs' deltas, the standard retail heuristic,
which is good enough for ranking candidates against each other. Liquidity
filtering (reject illiquid legs) happens in strategies/options/base.py's
nearest_by_delta and is re-checked here via is_liquid_structure before scoring,
per CLAUDE.md feature B ("reject illiquid: bid-ask > X% of mid").
"""

from __future__ import annotations

from dataclasses import dataclass, field

from omega_ib.broker.base import Contract, OrderRequest
from omega_ib.data.options import is_liquid
from omega_ib.strategies.options.base import OptionLeg, OptionStructure


def _leg_contract(leg: OptionLeg) -> Contract:
    return Contract(
        symbol=leg.quote.symbol,
        sec_type="OPT",
        expiry=leg.quote.expiry,
        strike=leg.quote.strike,
        right=leg.quote.right,
        leg_action=leg.action,
        leg_ratio=leg.ratio,
    )


def net_price(structure: OptionStructure) -> float:
    """Net price per combo unit: positive = net debit (you pay), negative = net credit (you receive)."""
    total = 0.0
    for leg in structure.legs:
        sign = 1 if leg.action == "BUY" else -1
        total += sign * leg.quote.mid * leg.ratio
    return total


def build_combo_order(structure: OptionStructure, quantity: int = 1, limit_price: float | None = None) -> OrderRequest:
    """quantity is the number of combo units (e.g. 1 iron condor). limit_price
    overrides the computed net_price() if given (e.g. a slightly better price to
    try first before submit_with_price_walk steps toward the mid)."""
    legs = [_leg_contract(leg) for leg in structure.legs]
    bag = Contract(symbol=structure.symbol, sec_type="BAG", legs=legs)
    net = limit_price if limit_price is not None else net_price(structure)
    action = "BUY" if net >= 0 else "SELL"
    return OrderRequest(contract=bag, action=action, quantity=quantity, order_type="LMT", limit_price=round(abs(net), 2))


def net_greeks(structure: OptionStructure) -> dict[str, float]:
    totals = {"delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0}
    for leg in structure.legs:
        sign = 1 if leg.action == "BUY" else -1
        totals["delta"] += sign * leg.quote.delta * leg.ratio
        totals["gamma"] += sign * leg.quote.gamma * leg.ratio
        totals["theta"] += sign * leg.quote.theta * leg.ratio
        totals["vega"] += sign * leg.quote.vega * leg.ratio
    return totals


def payoff_at_expiration(structure: OptionStructure, underlying_price: float) -> float:
    """Dollar P&L of one combo unit (100-share multiplier) at expiration, for a
    given underlying price, including the entry credit/debit."""
    intrinsic_total = 0.0
    for leg in structure.legs:
        if leg.quote.right == "C":
            intrinsic = max(0.0, underlying_price - leg.quote.strike)
        else:
            intrinsic = max(0.0, leg.quote.strike - underlying_price)
        sign = 1 if leg.action == "BUY" else -1
        intrinsic_total += sign * intrinsic * leg.ratio
    entry_credit = -net_price(structure)  # credit received (positive) or debit paid (negative)
    return (intrinsic_total + entry_credit) * 100


def payoff_curve(structure: OptionStructure, price_range: tuple[float, float], steps: int = 41) -> list[tuple[float, float]]:
    lo, hi = price_range
    step = (hi - lo) / (steps - 1) if steps > 1 else 0.0
    return [(lo + i * step, payoff_at_expiration(structure, lo + i * step)) for i in range(steps)]


def _default_price_range(structure: OptionStructure, pad_pct: float = 0.5) -> tuple[float, float]:
    strikes = [leg.quote.strike for leg in structure.legs]
    lo, hi = min(strikes), max(strikes)
    span = max(hi - lo, hi * 0.1, 1.0)
    return (max(0.01, lo - span * pad_pct), hi + span * pad_pct)


def probability_of_profit(structure: OptionStructure) -> float:
    """Retail delta-proxy heuristic, 0-1.

    Net-credit structures (CSP, covered call, bull put, bear call, iron condor)
    profit if the short legs expire OTM, so POP ~= 1 - avg(|short leg delta|).
    Net-debit structures (calendar, debit spreads) need the underlying to move
    in the anticipated direction, so POP ~= avg(|long leg delta|) as a rough
    proxy for "finishes ITM enough to profit."
    """
    if net_price(structure) <= 0:
        short_deltas = [abs(leg.quote.delta) for leg in structure.legs if leg.action == "SELL"]
        if not short_deltas:
            return 0.5
        return max(0.0, min(1.0, 1 - sum(short_deltas) / len(short_deltas)))
    long_deltas = [abs(leg.quote.delta) for leg in structure.legs if leg.action == "BUY"]
    if not long_deltas:
        return 0.5
    return max(0.0, min(1.0, sum(long_deltas) / len(long_deltas)))


@dataclass
class PayoffSummary:
    max_profit: float
    max_loss: float
    breakevens: list[float]
    pop: float
    ev: float
    net_greeks: dict[str, float] = field(default_factory=dict)


def summarize_payoff(structure: OptionStructure, price_range: tuple[float, float] | None = None) -> PayoffSummary:
    rng = price_range or _default_price_range(structure)
    curve = payoff_curve(structure, rng, steps=201)
    pnls = [p for _, p in curve]
    max_profit = max(pnls)
    max_loss = min(pnls)
    breakevens: list[float] = []
    for (p1, pnl1), (p2, pnl2) in zip(curve, curve[1:], strict=False):
        if pnl1 == 0:
            breakevens.append(p1)
        elif pnl1 * pnl2 < 0:  # strict sign change; pnl2 == 0 is handled by the next pair's pnl1 == 0 branch
            frac = -pnl1 / (pnl2 - pnl1)
            breakevens.append(p1 + frac * (p2 - p1))
    pop = probability_of_profit(structure)
    ev = pop * max_profit + (1 - pop) * max_loss
    return PayoffSummary(max_profit=max_profit, max_loss=max_loss, breakevens=breakevens, pop=pop, ev=ev, net_greeks=net_greeks(structure))


def return_on_risk(summary: PayoffSummary) -> float:
    if summary.max_loss >= 0:
        return float("inf") if summary.max_profit > 0 else 0.0
    return summary.max_profit / abs(summary.max_loss)


def is_liquid_structure(structure: OptionStructure, max_spread_pct: float = 0.10, min_open_interest: int = 50) -> bool:
    return all(is_liquid(leg.quote, max_spread_pct, min_open_interest) for leg in structure.legs)


def score_structure(summary: PayoffSummary) -> float:
    """Ranking score blending EV, POP, and theta (income structures favor decay).
    return_on_risk is capped so an uncapped/near-infinite ROR on a small-credit
    structure can't dominate the ranking."""
    theta = summary.net_greeks.get("theta", 0.0)
    ror = min(return_on_risk(summary), 10.0)
    return summary.ev * 0.5 + summary.pop * 100 * 0.3 + theta * 10 * 0.1 + ror * 0.1


@dataclass
class RankedStructure:
    structure: OptionStructure
    summary: PayoffSummary
    score: float


def rank_structures(
    structures: list[OptionStructure],
    max_spread_pct: float = 0.10,
    min_open_interest: int = 50,
) -> list[RankedStructure]:
    """Filters out illiquid structures, scores the rest, highest score first."""
    ranked = []
    for structure in structures:
        if not is_liquid_structure(structure, max_spread_pct, min_open_interest):
            continue
        summary = summarize_payoff(structure)
        ranked.append(RankedStructure(structure=structure, summary=summary, score=score_structure(summary)))
    return sorted(ranked, key=lambda r: r.score, reverse=True)

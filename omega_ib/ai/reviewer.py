"""Claude-powered pre-market plan, mid-session review, and EOD review.

CLAUDE.md rule 5: the AI layer is advisory only. It can approve, veto, or
tighten a proposed signal/position -- it can never loosen a risk limit or call
risk/guard.py or the broker directly. This is structurally enforced, not just
by convention: the review schema's only lever is `size_multiplier`, clamped to
[0.0, 1.0] by both the JSON schema sent to the model and a pydantic validator
on the way back, so it can only shrink what risk/guard.py already sized --
there is no field through which the AI could raise a limit, size up, or place
an order itself.

Every review call and its outcome (including API failures) is written to the
audit log and the ai_decisions table with a reason (CLAUDE.md rule 7). If the
Anthropic API is unreachable, misconfigured, or returns something that fails
schema validation, `review()` falls back to a no-op decision (action=
"approve", size_multiplier=1.0) for every symbol so the rule-based pipeline in
strategies/execution/guard keeps running completely unmodified -- the AI is
never a single point of failure for trading to continue.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field

from omega_ib.broker.base import AccountSummary as BrokerAccountSummary
from omega_ib.broker.base import Position
from omega_ib.config import Settings
from omega_ib.config import settings as default_settings
from omega_ib.store.db import session_scope, write_audit
from omega_ib.store.models import AIDecision
from omega_ib.strategies.equity.base import Signal

logger = logging.getLogger(__name__)

ReviewKind = Literal["pre_market", "mid_session", "eod"]
ReviewAction = Literal["approve", "veto", "tighten"]


class SignalReview(BaseModel):
    """One decision per signal/position. `size_multiplier` can only shrink
    (<=1.0) what risk/guard.py's own sizing already computed."""

    symbol: str
    action: ReviewAction
    size_multiplier: float = Field(default=1.0, ge=0.0, le=1.0)
    rationale: str = ""


class ReviewResponse(BaseModel):
    summary: str = ""
    reviews: list[SignalReview] = Field(default_factory=list)


TOOL_SCHEMA = {
    "name": "trading_review",
    "description": "Advisory review of proposed trading signals/positions. Can only approve, veto, or shrink size -- never raises a risk limit or increases size.",
    "input_schema": {
        "type": "object",
        "properties": {
            "summary": {"type": "string", "description": "One-paragraph overview of market conditions and overall rationale."},
            "reviews": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "symbol": {"type": "string"},
                        "action": {"type": "string", "enum": ["approve", "veto", "tighten"]},
                        "size_multiplier": {
                            "type": "number",
                            "minimum": 0.0,
                            "maximum": 1.0,
                            "description": "Multiplies the risk-guard-computed size. Must be <= 1.0 (cannot increase size).",
                        },
                        "rationale": {"type": "string"},
                    },
                    "required": ["symbol", "action"],
                },
            },
        },
        "required": ["summary", "reviews"],
    },
}


@dataclass
class ReviewOutcome:
    kind: ReviewKind
    response: ReviewResponse
    used_fallback: bool
    error: str = ""


def _fallback_response(symbols: list[str], reason: str) -> ReviewResponse:
    return ReviewResponse(
        summary=f"AI review unavailable ({reason}); falling back to rule-based approval.",
        reviews=[
            SignalReview(symbol=symbol, action="approve", size_multiplier=1.0, rationale="fallback: AI unavailable")
            for symbol in symbols
        ],
    )


def _format_signals(signals: list[Signal]) -> str:
    lines = []
    for s in signals:
        lines.append(
            f"- {s.symbol} ({s.strategy}, {s.direction}): entry {s.entry_price:.2f}, "
            f"stop {s.stop_price:.2f}, target {s.target_price:.2f}, score {s.score:.2f}. {s.reason}"
        )
    return "\n".join(lines) or "(none)"


def _format_positions(positions: list[Position]) -> str:
    lines = [f"- {p.symbol}: qty {p.quantity:g} @ {p.avg_cost:.2f}, mark {p.market_price:.2f}, P&L ${p.unrealized_pnl:,.2f}" for p in positions]
    return "\n".join(lines) or "(none)"


def build_pre_market_prompt(signals: list[Signal], account: BrokerAccountSummary) -> str:
    return (
        "You are a risk-averse trading assistant reviewing today's pre-market signal candidates "
        "for an automated equity trading system. You may approve, veto, or tighten (shrink size) "
        "each signal -- you cannot increase size or override any risk limit; sizing and final "
        "order placement are handled separately by a hard-coded risk guard that will re-check "
        "every limit regardless of what you say.\n\n"
        f"Account NAV: ${account.nav:,.2f}. Day P&L so far: ${account.day_pnl:,.2f}.\n\n"
        f"Candidate signals:\n{_format_signals(signals)}\n\n"
        "Respond with a review for every symbol listed above."
    )


def build_mid_session_prompt(positions: list[Position], day_pnl_pct: float) -> str:
    return (
        "You are reviewing open positions mid-session for an automated equity trading system. "
        "You may approve (hold), veto (flatten now), or tighten (reduce size) each position -- "
        "you cannot increase size or override any risk limit.\n\n"
        f"Day P&L so far: {day_pnl_pct:.2%} of NAV.\n\n"
        f"Open positions:\n{_format_positions(positions)}\n\n"
        "Respond with a review for every symbol listed above."
    )


def build_eod_prompt(trades_today: list[dict], account: BrokerAccountSummary) -> str:
    lines = [f"- {t.get('symbol', '?')}: {t.get('strategy', '?')} realized P&L ${t.get('pnl', 0.0):,.2f}" for t in trades_today]
    trades_desc = "\n".join(lines) or "(no trades today)"
    return (
        "You are reviewing today's closed trades end-of-day for an automated equity trading "
        "system. Summarize what worked and flag any pattern worth vetoing or tightening "
        "tomorrow -- you cannot change any risk limit; this is a narrative/advisory review only.\n\n"
        f"Account NAV: ${account.nav:,.2f}. Day P&L: ${account.day_pnl:,.2f}.\n\n"
        f"Closed trades:\n{trades_desc}\n\n"
        "Respond with a review entry per symbol traded today (action can be 'approve' as a "
        "no-objection acknowledgement)."
    )


def apply_reviews_to_signals(signals: list[Signal], reviews: list[SignalReview]) -> list[tuple[Signal, float]]:
    """(signal, size_multiplier) pairs for every signal the AI didn't veto. A
    signal with no matching review passes through unchanged (multiplier=1.0) --
    the AI is advisory, not gating; if it didn't opine, rule-based execution
    proceeds as if the AI were absent."""
    review_by_symbol = {r.symbol: r for r in reviews}
    kept: list[tuple[Signal, float]] = []
    for s in signals:
        review = review_by_symbol.get(s.symbol)
        if review is None:
            kept.append((s, 1.0))
            continue
        if review.action == "veto":
            continue
        kept.append((s, review.size_multiplier if review.action == "tighten" else 1.0))
    return kept


class AIReviewer:
    def __init__(self, settings: Settings | None = None, client=None) -> None:
        self.settings = settings or default_settings
        self._client = client  # injectable for tests; lazily created for real use

    def _get_client(self):
        if self._client is not None:
            return self._client
        if not self.settings.anthropic_api_key:
            raise RuntimeError("ANTHROPIC_API_KEY not configured")
        import anthropic

        self._client = anthropic.Anthropic(api_key=self.settings.anthropic_api_key)
        return self._client

    def review(self, kind: ReviewKind, prompt: str, symbols: list[str]) -> ReviewOutcome:
        """Runs one review call. Always returns a usable ReviewResponse: falls
        back to rule-based approval (never blocks trading) if the API call
        fails or the response doesn't validate against the schema."""
        try:
            client = self._get_client()
            message = client.messages.create(
                model=self.settings.ai_model,
                max_tokens=1536,
                tools=[TOOL_SCHEMA],
                tool_choice={"type": "tool", "name": "trading_review"},
                messages=[{"role": "user", "content": prompt}],
            )
            tool_use = next(block for block in message.content if getattr(block, "type", None) == "tool_use")
            response = ReviewResponse.model_validate(tool_use.input)
            outcome = ReviewOutcome(kind=kind, response=response, used_fallback=False)
            self._log(outcome, raw=json.dumps(tool_use.input))
            return outcome
        except Exception as exc:  # noqa: BLE001 - the AI layer must never take trading down
            logger.error("AI review failed (%s), falling back to rule-based approval: %s", kind, exc)
            response = _fallback_response(symbols, reason=str(exc))
            outcome = ReviewOutcome(kind=kind, response=response, used_fallback=True, error=str(exc))
            self._log(outcome, raw=str(exc))
            return outcome

    def pre_market_plan(self, signals: list[Signal], account: BrokerAccountSummary) -> ReviewOutcome:
        return self.review("pre_market", build_pre_market_prompt(signals, account), [s.symbol for s in signals])

    def mid_session_review(self, positions: list[Position], day_pnl_pct: float) -> ReviewOutcome:
        return self.review("mid_session", build_mid_session_prompt(positions, day_pnl_pct), [p.symbol for p in positions])

    def eod_review(self, trades_today: list[dict], account: BrokerAccountSummary) -> ReviewOutcome:
        symbols = [t.get("symbol", "") for t in trades_today]
        return self.review("eod", build_eod_prompt(trades_today, account), symbols)

    def _log(self, outcome: ReviewOutcome, raw: str) -> None:
        event_type = "ai_review_fallback" if outcome.used_fallback else "ai_review"
        write_audit(
            event_type,
            outcome.response.summary or outcome.error,
            {"kind": outcome.kind, "reviews": [r.model_dump() for r in outcome.response.reviews]},
        )
        with session_scope() as session:
            if outcome.response.reviews:
                for r in outcome.response.reviews:
                    session.add(AIDecision(kind=outcome.kind, symbol=r.symbol, action=r.action, rationale=r.rationale, raw_response=raw))
            else:
                session.add(AIDecision(kind=outcome.kind, symbol="", action="no_action", rationale=outcome.response.summary, raw_response=raw))

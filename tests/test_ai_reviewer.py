from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from omega_ib.ai.reviewer import (
    AIReviewer,
    ReviewResponse,
    SignalReview,
    apply_reviews_to_signals,
    build_eod_prompt,
    build_mid_session_prompt,
    build_pre_market_prompt,
)
from omega_ib.broker.base import AccountSummary, Position
from omega_ib.config import Settings
from omega_ib.store.db import session_scope
from omega_ib.store.models import AIDecision, AuditLog
from omega_ib.strategies.equity.base import Signal


def _signal(symbol="AAPL", score=1.0):
    return Signal(
        symbol=symbol, strategy="momentum_breakout", direction="long", score=score,
        entry_price=100.0, stop_price=95.0, target_price=110.0, reason="test signal",
    )


class _FakeClientOK:
    def __init__(self, tool_input: dict):
        self._tool_input = tool_input
        self.messages = SimpleNamespace(create=self._create)
        self.calls = []

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        tool_use = SimpleNamespace(type="tool_use", input=self._tool_input)
        return SimpleNamespace(content=[tool_use])


class _FakeClientRaises:
    def __init__(self, exc: Exception):
        self.messages = SimpleNamespace(create=self._create)
        self._exc = exc

    def _create(self, **kwargs):
        raise self._exc


def test_review_success_parses_and_logs():
    tool_input = {
        "summary": "Market looks fine.",
        "reviews": [{"symbol": "AAPL", "action": "approve", "size_multiplier": 1.0, "rationale": "ok"}],
    }
    client = _FakeClientOK(tool_input)
    reviewer = AIReviewer(settings=Settings(), client=client)
    outcome = reviewer.review("pre_market", "some prompt", ["AAPL"])
    assert outcome.used_fallback is False
    assert outcome.response.summary == "Market looks fine."
    assert outcome.response.reviews[0].action == "approve"
    with session_scope() as session:
        decisions = session.query(AIDecision).all()
        assert len(decisions) == 1
        assert decisions[0].symbol == "AAPL"
        audit_rows = session.query(AuditLog).filter_by(event_type="ai_review").all()
        assert len(audit_rows) == 1


def test_review_falls_back_on_api_error():
    client = _FakeClientRaises(ConnectionError("no network"))
    reviewer = AIReviewer(settings=Settings(), client=client)
    outcome = reviewer.review("mid_session", "some prompt", ["AAPL", "MSFT"])
    assert outcome.used_fallback is True
    assert len(outcome.response.reviews) == 2
    assert all(r.action == "approve" and r.size_multiplier == 1.0 for r in outcome.response.reviews)
    with session_scope() as session:
        fallback_rows = session.query(AuditLog).filter_by(event_type="ai_review_fallback").all()
        assert len(fallback_rows) == 1


def test_review_falls_back_when_no_client_and_no_api_key():
    reviewer = AIReviewer(settings=Settings(anthropic_api_key=""))
    outcome = reviewer.review("eod", "prompt", ["AAPL"])
    assert outcome.used_fallback is True
    assert outcome.response.reviews[0].symbol == "AAPL"


def test_review_falls_back_on_schema_validation_failure():
    # missing required "action" field for the review entry
    tool_input = {"summary": "bad", "reviews": [{"symbol": "AAPL"}]}
    client = _FakeClientOK(tool_input)
    reviewer = AIReviewer(settings=Settings(), client=client)
    outcome = reviewer.review("pre_market", "prompt", ["AAPL"])
    assert outcome.used_fallback is True


def test_review_falls_back_when_size_multiplier_exceeds_one():
    # a model that tries to "loosen" sizing above 1.0 must be rejected, not honored
    tool_input = {
        "summary": "trying to size up",
        "reviews": [{"symbol": "AAPL", "action": "tighten", "size_multiplier": 2.0}],
    }
    client = _FakeClientOK(tool_input)
    reviewer = AIReviewer(settings=Settings(), client=client)
    outcome = reviewer.review("pre_market", "prompt", ["AAPL"])
    assert outcome.used_fallback is True


def test_signal_review_rejects_multiplier_above_one_directly():
    with pytest.raises(ValidationError):
        SignalReview(symbol="AAPL", action="tighten", size_multiplier=1.5)


def test_apply_reviews_to_signals_veto_removes_signal():
    signals = [_signal("AAPL"), _signal("MSFT")]
    reviews = [SignalReview(symbol="AAPL", action="veto")]
    kept = apply_reviews_to_signals(signals, reviews)
    symbols = [s.symbol for s, _mult in kept]
    assert symbols == ["MSFT"]


def test_apply_reviews_to_signals_tighten_applies_multiplier():
    signals = [_signal("AAPL")]
    reviews = [SignalReview(symbol="AAPL", action="tighten", size_multiplier=0.5)]
    kept = apply_reviews_to_signals(signals, reviews)
    assert kept == [(signals[0], 0.5)]


def test_apply_reviews_to_signals_unreviewed_passes_through():
    signals = [_signal("AAPL")]
    kept = apply_reviews_to_signals(signals, reviews=[])
    assert kept == [(signals[0], 1.0)]


def test_apply_reviews_to_signals_approve_uses_full_size():
    signals = [_signal("AAPL")]
    reviews = [SignalReview(symbol="AAPL", action="approve", size_multiplier=0.3)]
    kept = apply_reviews_to_signals(signals, reviews)
    # approve ignores any size_multiplier the model set -- only "tighten" shrinks size
    assert kept == [(signals[0], 1.0)]


def test_pre_market_plan_wrapper():
    tool_input = {"summary": "ok", "reviews": [{"symbol": "AAPL", "action": "approve"}]}
    client = _FakeClientOK(tool_input)
    reviewer = AIReviewer(settings=Settings(), client=client)
    account = AccountSummary(nav=100_000.0, cash=100_000.0, buying_power=100_000.0, day_pnl=500.0)
    outcome = reviewer.pre_market_plan([_signal("AAPL")], account)
    assert outcome.kind == "pre_market"
    assert "AAPL" in client.calls[0]["messages"][0]["content"]


def test_mid_session_review_wrapper():
    tool_input = {"summary": "ok", "reviews": [{"symbol": "AAPL", "action": "approve"}]}
    client = _FakeClientOK(tool_input)
    reviewer = AIReviewer(settings=Settings(), client=client)
    position = Position(symbol="AAPL", sec_type="STK", quantity=10, avg_cost=100.0, market_price=105.0, unrealized_pnl=50.0)
    outcome = reviewer.mid_session_review([position], day_pnl_pct=0.01)
    assert outcome.kind == "mid_session"


def test_eod_review_wrapper():
    tool_input = {"summary": "ok", "reviews": [{"symbol": "AAPL", "action": "approve"}]}
    client = _FakeClientOK(tool_input)
    reviewer = AIReviewer(settings=Settings(), client=client)
    account = AccountSummary(nav=100_000.0, cash=100_000.0, buying_power=100_000.0)
    outcome = reviewer.eod_review([{"symbol": "AAPL", "strategy": "momentum_breakout", "pnl": 120.0}], account)
    assert outcome.kind == "eod"


def test_build_pre_market_prompt_contains_signal_details():
    prompt = build_pre_market_prompt([_signal("AAPL")], AccountSummary(nav=100_000.0, cash=100_000.0, buying_power=100_000.0))
    assert "AAPL" in prompt
    assert "momentum_breakout" in prompt


def test_build_mid_session_prompt_contains_position_details():
    position = Position(symbol="AAPL", sec_type="STK", quantity=10, avg_cost=100.0, market_price=105.0, unrealized_pnl=50.0)
    prompt = build_mid_session_prompt([position], day_pnl_pct=0.01)
    assert "AAPL" in prompt


def test_build_mid_session_prompt_no_positions():
    prompt = build_mid_session_prompt([], day_pnl_pct=0.0)
    assert "(none)" in prompt


def test_build_eod_prompt_contains_trades():
    prompt = build_eod_prompt([{"symbol": "AAPL", "strategy": "momentum_breakout", "pnl": 100.0}], AccountSummary(nav=100_000.0, cash=100_000.0, buying_power=100_000.0))
    assert "AAPL" in prompt


def test_review_response_defaults_to_empty_reviews():
    response = ReviewResponse()
    assert response.reviews == []
    assert response.summary == ""

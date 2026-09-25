import datetime as dt

from omega_ib.data.market import StaticEarningsCalendar
from omega_ib.lifecycle.eod import (
    earnings_proximity_decision,
    eod_decisions_for_position,
    is_leveraged_etf,
    leveraged_etf_flatten_decision,
    overnight_hold_decision,
)


def test_is_leveraged_etf():
    assert is_leveraged_etf("TQQQ")
    assert is_leveraged_etf("tqqq")
    assert not is_leveraged_etf("AAPL")


def test_leveraged_etf_flatten_decision():
    decision = leveraged_etf_flatten_decision("SOXL")
    assert decision is not None
    assert decision.action == "flatten"
    assert leveraged_etf_flatten_decision("AAPL") is None


def test_earnings_proximity_decision_within_buffer():
    cal = StaticEarningsCalendar({"AAPL": dt.date(2026, 1, 30)})
    decision = earnings_proximity_decision("AAPL", dt.date(2026, 1, 29), cal, min_days_buffer=1)
    assert decision is not None
    assert "earnings" in decision.reason


def test_earnings_proximity_decision_outside_buffer():
    cal = StaticEarningsCalendar({"AAPL": dt.date(2026, 1, 30)})
    decision = earnings_proximity_decision("AAPL", dt.date(2026, 1, 1), cal, min_days_buffer=1)
    assert decision is None


def test_earnings_proximity_decision_no_earnings_known():
    cal = StaticEarningsCalendar()
    assert earnings_proximity_decision("AAPL", dt.date(2026, 1, 1), cal) is None


def test_overnight_hold_decision_flattens_large_intraday_loss():
    decision = overnight_hold_decision("AAPL", unrealized_pnl_pct=-0.05, stop_loss_pct=-0.03, entered_today=True)
    assert decision is not None
    assert decision.action == "flatten"


def test_overnight_hold_decision_holds_when_not_entered_today():
    decision = overnight_hold_decision("AAPL", unrealized_pnl_pct=-0.05, stop_loss_pct=-0.03, entered_today=False)
    assert decision is None


def test_overnight_hold_decision_holds_small_loss():
    decision = overnight_hold_decision("AAPL", unrealized_pnl_pct=-0.01, stop_loss_pct=-0.03, entered_today=True)
    assert decision is None


def test_eod_decisions_for_position_leveraged_etf_wins():
    cal = StaticEarningsCalendar()
    decision = eod_decisions_for_position("TQQQ", dt.date(2026, 1, 1), cal)
    assert decision.action == "flatten"
    assert "leveraged" in decision.reason


def test_eod_decisions_for_position_holds_by_default():
    cal = StaticEarningsCalendar()
    decision = eod_decisions_for_position("AAPL", dt.date(2026, 1, 1), cal)
    assert decision.action == "hold"

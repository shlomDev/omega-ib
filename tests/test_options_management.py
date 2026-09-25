import datetime as dt

from omega_ib.lifecycle.eod import days_to_expiration, options_management_decision


def test_days_to_expiration():
    assert days_to_expiration("20261218", dt.date(2026, 12, 1)) == 17


def test_credit_take_profit_at_50pct():
    decision = options_management_decision(
        "AAPL", "20270301", dt.date(2026, 12, 1), entry_net_price=-3.0, current_net_price=1.5
    )
    assert decision.action == "flatten"
    assert "take profit" in decision.reason


def test_credit_stop_loss_at_2x_credit():
    decision = options_management_decision(
        "AAPL", "20270301", dt.date(2026, 12, 1), entry_net_price=-3.0, current_net_price=6.0
    )
    assert decision.action == "flatten"
    assert "stop loss" in decision.reason


def test_credit_rolls_at_21_dte():
    decision = options_management_decision(
        "AAPL", "20261210", dt.date(2026, 12, 1), entry_net_price=-3.0, current_net_price=2.9
    )
    assert decision.action == "roll"
    assert "DTE" in decision.reason


def test_credit_holds_when_nothing_triggers():
    decision = options_management_decision(
        "AAPL", "20270301", dt.date(2026, 12, 1), entry_net_price=-3.0, current_net_price=2.9
    )
    assert decision.action == "hold"


def test_debit_take_profit():
    decision = options_management_decision(
        "AAPL", "20270301", dt.date(2026, 12, 1), entry_net_price=2.5, current_net_price=-4.0
    )
    assert decision.action == "flatten"
    assert "gain on debit" in decision.reason


def test_debit_rolls_at_21_dte_without_profit():
    decision = options_management_decision(
        "AAPL", "20261210", dt.date(2026, 12, 1), entry_net_price=2.5, current_net_price=-2.6
    )
    assert decision.action == "roll"

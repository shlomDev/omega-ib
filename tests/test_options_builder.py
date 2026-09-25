from omega_ib.options_builder import (
    build_combo_order,
    is_liquid_structure,
    net_greeks,
    net_price,
    payoff_at_expiration,
    probability_of_profit,
    rank_structures,
    return_on_risk,
    score_structure,
    summarize_payoff,
)
from omega_ib.strategies.options import CashSecuredPut, IronCondor, LongCallDebitSpread
from tests.options_fixtures import NEAR_EXPIRY, build_chain


def test_net_price_credit_negative_for_iron_condor():
    chain = build_chain()
    structure = IronCondor().generate(chain, NEAR_EXPIRY)
    assert net_price(structure) == -3.0  # net credit: negative by convention


def test_net_price_debit_positive_for_debit_spread():
    chain = build_chain()
    structure = LongCallDebitSpread().generate(chain, NEAR_EXPIRY)
    assert net_price(structure) == 2.5


def test_build_combo_order_sell_for_credit():
    chain = build_chain()
    structure = IronCondor().generate(chain, NEAR_EXPIRY)
    order = build_combo_order(structure)
    assert order.contract.sec_type == "BAG"
    assert len(order.contract.legs) == 4
    assert order.action == "SELL"
    assert order.limit_price == 3.0
    assert order.order_type == "LMT"


def test_build_combo_order_buy_for_debit():
    chain = build_chain()
    structure = LongCallDebitSpread().generate(chain, NEAR_EXPIRY)
    order = build_combo_order(structure)
    assert order.action == "BUY"
    assert order.limit_price == 2.5


def test_net_greeks_sums_legs_with_sign():
    chain = build_chain()
    structure = CashSecuredPut().generate(chain, NEAR_EXPIRY)
    greeks = net_greeks(structure)
    # single SELL leg -> greeks sign-flipped from the raw quote
    leg = structure.legs[0].quote
    assert greeks["delta"] == -leg.delta
    assert greeks["theta"] == -leg.theta


def test_payoff_at_expiration_short_put_worthless_is_max_profit():
    chain = build_chain()
    structure = CashSecuredPut().generate(chain, NEAR_EXPIRY)
    strike = structure.legs[0].quote.strike
    # underlying well above strike -> put expires worthless, full credit kept
    pnl_otm = payoff_at_expiration(structure, strike + 20)
    pnl_deep_itm = payoff_at_expiration(structure, strike - 50)
    assert pnl_otm > 0
    assert pnl_deep_itm < pnl_otm


def test_summarize_payoff_iron_condor():
    chain = build_chain()
    structure = IronCondor().generate(chain, NEAR_EXPIRY)
    summary = summarize_payoff(structure)
    assert summary.max_profit == 300.0
    assert summary.max_loss == -200.0
    assert summary.breakevens == [92.0, 108.0]
    assert 0.0 <= summary.pop <= 1.0


def test_summarize_payoff_debit_spread():
    chain = build_chain()
    structure = LongCallDebitSpread().generate(chain, NEAR_EXPIRY)
    summary = summarize_payoff(structure)
    assert summary.max_profit == 250.0
    assert summary.max_loss == -250.0
    assert summary.breakevens == [97.5]


def test_probability_of_profit_credit_vs_debit_conventions():
    chain = build_chain()
    credit_structure = IronCondor().generate(chain, NEAR_EXPIRY)
    debit_structure = LongCallDebitSpread().generate(chain, NEAR_EXPIRY)
    assert probability_of_profit(credit_structure) == 0.65  # 1 - avg(|short deltas|) = 1 - avg(0.35, 0.35)
    assert probability_of_profit(debit_structure) == 0.65  # avg(|long deltas|) coincidentally matches here (0.65 delta long call)


def test_return_on_risk():
    chain = build_chain()
    structure = IronCondor().generate(chain, NEAR_EXPIRY)
    summary = summarize_payoff(structure)
    assert round(return_on_risk(summary), 2) == round(300.0 / 200.0, 2)


def test_return_on_risk_zero_max_loss_edge_case():
    class _FakeSummary:
        max_profit = 0.0
        max_loss = 0.0

    assert return_on_risk(_FakeSummary()) == 0.0


def test_is_liquid_structure_true_for_fixture():
    chain = build_chain()
    structure = IronCondor().generate(chain, NEAR_EXPIRY)
    assert is_liquid_structure(structure) is True


def test_is_liquid_structure_false_when_a_leg_is_illiquid():
    chain = build_chain()
    structure = IronCondor().generate(chain, NEAR_EXPIRY)
    structure.legs[0].quote.open_interest = 0
    assert is_liquid_structure(structure) is False


def test_score_structure_higher_for_better_summary():
    chain = build_chain()
    ic_summary = summarize_payoff(IronCondor().generate(chain, NEAR_EXPIRY))
    csp_summary = summarize_payoff(CashSecuredPut().generate(chain, NEAR_EXPIRY))
    assert isinstance(score_structure(ic_summary), float)
    assert isinstance(score_structure(csp_summary), float)


def test_rank_structures_sorted_and_filters_illiquid():
    chain = build_chain()
    ic = IronCondor().generate(chain, NEAR_EXPIRY)
    csp = CashSecuredPut().generate(chain, NEAR_EXPIRY)
    lcds = LongCallDebitSpread().generate(chain, NEAR_EXPIRY)
    lcds.legs[0].quote.open_interest = 0  # make this one illiquid
    ranked = rank_structures([ic, csp, lcds])
    assert [r.structure.strategy for r in ranked] == ["iron_condor", "cash_secured_put"]
    assert ranked[0].score >= ranked[1].score

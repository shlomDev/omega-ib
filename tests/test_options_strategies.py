from omega_ib.data.options import OptionChain
from omega_ib.strategies.options import (
    BearCallSpread,
    BullPutSpread,
    CalendarSpread,
    CashSecuredPut,
    CoveredCall,
    IronCondor,
    LongCallDebitSpread,
    LongPutDebitSpread,
    nearest_by_delta,
)
from tests.options_fixtures import FAR_EXPIRY, NEAR_EXPIRY, build_chain


def test_cash_secured_put_picks_nearest_delta_put():
    chain = build_chain()
    signal = CashSecuredPut().generate(chain, NEAR_EXPIRY)
    assert signal is not None
    assert len(signal.legs) == 1
    leg = signal.legs[0]
    assert leg.action == "SELL"
    assert leg.quote.right == "P"
    assert leg.quote.strike == 95.0


def test_covered_call_picks_nearest_delta_call():
    chain = build_chain()
    signal = CoveredCall().generate(chain, NEAR_EXPIRY)
    assert signal is not None
    leg = signal.legs[0]
    assert leg.action == "SELL"
    assert leg.quote.right == "C"
    assert leg.quote.strike == 105.0


def test_bull_put_spread_legs():
    chain = build_chain()
    signal = BullPutSpread().generate(chain, NEAR_EXPIRY)
    assert signal is not None
    short_leg, long_leg = signal.legs
    assert short_leg.action == "SELL" and short_leg.quote.strike == 95.0
    assert long_leg.action == "BUY" and long_leg.quote.strike == 90.0


def test_bear_call_spread_legs():
    chain = build_chain()
    signal = BearCallSpread().generate(chain, NEAR_EXPIRY)
    assert signal is not None
    short_leg, long_leg = signal.legs
    assert short_leg.action == "SELL" and short_leg.quote.strike == 105.0
    assert long_leg.action == "BUY" and long_leg.quote.strike == 110.0


def test_iron_condor_combines_both_spreads():
    chain = build_chain()
    signal = IronCondor().generate(chain, NEAR_EXPIRY)
    assert signal is not None
    assert len(signal.legs) == 4
    strikes = sorted(leg.quote.strike for leg in signal.legs)
    assert strikes == [90.0, 95.0, 105.0, 110.0]


def test_iron_condor_none_if_either_side_fails():
    chain = build_chain()
    # Missing the far wing strikes forces both sides to fail.
    narrow = OptionChain(
        symbol="AAPL",
        underlying_price=100.0,
        quotes=[q for q in chain.quotes if q.strike in (95.0, 105.0)],
    )
    assert IronCondor().generate(narrow, NEAR_EXPIRY) is None


def test_calendar_spread_uses_next_expiry():
    chain = build_chain()
    signal = CalendarSpread().generate(chain, NEAR_EXPIRY)
    assert signal is not None
    short_leg, long_leg = signal.legs
    assert short_leg.action == "SELL" and short_leg.quote.expiry == NEAR_EXPIRY
    assert long_leg.action == "BUY" and long_leg.quote.expiry == FAR_EXPIRY
    assert short_leg.quote.strike == long_leg.quote.strike == 100.0


def test_calendar_spread_none_on_last_expiry():
    chain = build_chain()
    assert CalendarSpread().generate(chain, FAR_EXPIRY) is None


def test_long_call_debit_spread_legs():
    chain = build_chain()
    signal = LongCallDebitSpread().generate(chain, NEAR_EXPIRY)
    assert signal is not None
    long_leg, short_leg = signal.legs
    assert long_leg.action == "BUY" and long_leg.quote.strike == 95.0
    assert short_leg.action == "SELL" and short_leg.quote.strike == 100.0


def test_long_put_debit_spread_legs():
    chain = build_chain()
    signal = LongPutDebitSpread().generate(chain, NEAR_EXPIRY)
    assert signal is not None
    long_leg, short_leg = signal.legs
    assert long_leg.action == "BUY" and long_leg.quote.strike == 105.0
    assert short_leg.action == "SELL" and short_leg.quote.strike == 100.0


def test_nearest_by_delta_none_when_nothing_liquid():
    chain = build_chain()
    illiquid = [q for q in chain.by_expiry(NEAR_EXPIRY) if q.right == "P"]
    for q in illiquid:
        q.open_interest = 0
    assert nearest_by_delta(illiquid, -0.30) is None


def test_nearest_by_delta_none_when_too_far_from_target():
    chain = build_chain()
    puts = [q for q in chain.by_expiry(NEAR_EXPIRY) if q.right == "P"]
    assert nearest_by_delta(puts, target_delta=-0.99, max_delta_distance=0.01) is None

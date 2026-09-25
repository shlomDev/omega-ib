from omega_ib.strategies.options.base import OptionLeg, OptionsStrategy, OptionStructure, nearest_by_delta
from omega_ib.strategies.options.bear_call_spread import BearCallSpread
from omega_ib.strategies.options.bull_put_spread import BullPutSpread
from omega_ib.strategies.options.calendar_spread import CalendarSpread
from omega_ib.strategies.options.cash_secured_put import CashSecuredPut
from omega_ib.strategies.options.covered_call import CoveredCall
from omega_ib.strategies.options.debit_spreads import LongCallDebitSpread, LongPutDebitSpread
from omega_ib.strategies.options.iron_condor import IronCondor

ALL_OPTIONS_STRATEGIES: list[OptionsStrategy] = [
    CashSecuredPut(),
    CoveredCall(),
    BullPutSpread(),
    BearCallSpread(),
    IronCondor(),
    CalendarSpread(),
    LongCallDebitSpread(),
    LongPutDebitSpread(),
]

__all__ = [
    "ALL_OPTIONS_STRATEGIES",
    "BearCallSpread",
    "BullPutSpread",
    "CalendarSpread",
    "CashSecuredPut",
    "CoveredCall",
    "IronCondor",
    "LongCallDebitSpread",
    "LongPutDebitSpread",
    "OptionLeg",
    "OptionStructure",
    "OptionsStrategy",
    "nearest_by_delta",
]

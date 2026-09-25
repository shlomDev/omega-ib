"""End-to-end: strategy -> options_builder -> risk/guard -> broker, on FakeBroker
(paper-equivalent). Confirms combo (BAG) orders flow through the same guarded
path as equities, and that the naked-short-call check and options contract caps
apply to combo orders exactly as they do to single-leg orders.
"""

from omega_ib.broker.fake import FakeBroker
from omega_ib.config import Settings
from omega_ib.options_builder import build_combo_order
from omega_ib.risk.guard import GuardContext, GuardRejection, RiskGuard
from omega_ib.strategies.options import BearCallSpread, IronCondor
from tests.options_fixtures import NEAR_EXPIRY, build_chain


def _guard(tmp_path, **overrides):
    broker = FakeBroker()
    broker.connect()
    settings = Settings(kill_switch_file=str(tmp_path / "KILL"), **overrides)
    return RiskGuard(broker, settings), broker


def test_iron_condor_combo_order_placed_through_guard(tmp_path):
    guard, broker = _guard(tmp_path)
    chain = build_chain()
    structure = IronCondor().generate(chain, NEAR_EXPIRY)
    order = build_combo_order(structure, quantity=2)
    status = guard.place_order(order, GuardContext(nav=100_000.0, is_new_position=True))
    assert status.status == "filled"


def test_bear_call_spread_is_not_flagged_as_naked(tmp_path):
    """The long call leg covers the short call, so this must NOT trip the
    naked-short-call guard check that blocks uncovered SELL C legs."""
    guard, broker = _guard(tmp_path)
    chain = build_chain()
    structure = BearCallSpread().generate(chain, NEAR_EXPIRY)
    order = build_combo_order(structure)
    status = guard.place_order(order, GuardContext(nav=100_000.0, is_new_position=True))
    assert status.status == "filled"


def test_combo_order_respects_max_options_contracts_per_order(tmp_path):
    guard, broker = _guard(tmp_path, max_options_contracts_per_order=1)
    chain = build_chain()
    structure = IronCondor().generate(chain, NEAR_EXPIRY)
    order = build_combo_order(structure, quantity=5)
    try:
        guard.place_order(order, GuardContext(nav=100_000.0, is_new_position=True))
        raised = False
    except GuardRejection as exc:
        raised = True
        assert "max_options_contracts_per_order" in exc.reason
    assert raised

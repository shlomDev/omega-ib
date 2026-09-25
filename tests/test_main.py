import pandas as pd

from omega_ib.broker.base import Contract, OrderRequest
from omega_ib.broker.fake import FakeBroker
from omega_ib.config import Settings
from omega_ib.data.market import FakeMarketData
from omega_ib.main import (
    AppState,
    build_market_data,
    run_eod_management,
    run_mid_session_review,
    run_pre_market_plan,
)


def _state(tmp_path, starting_nav=100_000.0, **overrides):
    settings = Settings(kill_switch_file=str(tmp_path / "KILL"), **overrides)
    broker = FakeBroker(starting_nav=starting_nav)
    broker.connect()
    return AppState(settings, broker), broker


def test_build_market_data_returns_fake_for_fake_broker():
    broker = FakeBroker()
    assert isinstance(build_market_data(broker), FakeMarketData)


def test_app_state_wires_guard_and_web_app(tmp_path):
    state, broker = _state(tmp_path)
    assert state.guard.broker is broker
    assert state.reviewer is None  # no ANTHROPIC_API_KEY configured
    assert state.web_app is not None


def _breakout_bars():
    rows = [dict(open=100, high=101, low=99, close=100, volume=1000) for _ in range(21)]
    rows.append(dict(open=104, high=110, low=100, close=108, volume=3000))
    return pd.DataFrame(rows)


def test_run_pre_market_plan_places_one_bracket_per_symbol(tmp_path):
    state, broker = _state(tmp_path)
    state.market_data.set_bars("AAPL", _breakout_bars())

    placed = run_pre_market_plan(state, universe=["AAPL"])

    assert placed == 1
    positions = broker.positions()
    assert len(positions) == 1
    assert positions[0].symbol == "AAPL"
    assert positions[0].quantity > 0
    open_orders = broker.open_orders()
    assert len(open_orders) == 2  # stop + target both pending


def test_run_pre_market_plan_no_signals_is_a_safe_noop(tmp_path):
    state, broker = _state(tmp_path)
    state.market_data.set_bars("AAPL", pd.DataFrame([dict(open=100, high=101, low=99, close=100, volume=1000) for _ in range(30)]))

    placed = run_pre_market_plan(state, universe=["AAPL"])

    assert placed == 0
    assert broker.positions() == []


def test_run_pre_market_plan_bracket_resolves_on_target(tmp_path):
    state, broker = _state(tmp_path)
    state.market_data.set_bars("AAPL", _breakout_bars())
    run_pre_market_plan(state, universe=["AAPL"])

    broker.set_price("AAPL", 130.0)

    assert broker.positions() == []
    assert broker.open_orders() == []
    assert broker.realized_pnl > 0


def test_run_eod_management_flattens_leveraged_etf(tmp_path):
    state, broker = _state(tmp_path)
    broker.place_order(OrderRequest(contract=Contract(symbol="TQQQ"), action="BUY", quantity=10, limit_price=50.0))

    flattened = run_eod_management(state)

    assert flattened == 1
    assert broker.positions() == []


def test_run_eod_management_holds_normal_position(tmp_path):
    state, broker = _state(tmp_path)
    broker.place_order(OrderRequest(contract=Contract(symbol="AAPL"), action="BUY", quantity=10, limit_price=100.0))

    flattened = run_eod_management(state)

    assert flattened == 0
    assert len(broker.positions()) == 1


def test_run_mid_session_review_noop_without_reviewer(tmp_path):
    state, broker = _state(tmp_path)
    # Should not raise even though state.reviewer is None (no API key configured).
    run_mid_session_review(state)

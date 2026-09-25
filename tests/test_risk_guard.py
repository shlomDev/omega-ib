import pytest

from omega_ib.broker.base import Contract, OrderRequest
from omega_ib.broker.fake import FakeBroker
from omega_ib.config import LIVE_CONFIRM_PHRASE, Settings, TradingMode
from omega_ib.risk.guard import (
    GuardContext,
    GuardRejection,
    RiskGuard,
    atr_stop_price,
    fixed_fractional_size,
    size_by_fixed_fractional_atr,
)


def _settings(tmp_path, **overrides):
    kwargs = dict(kill_switch_file=str(tmp_path / "KILL"))
    kwargs.update(overrides)
    return Settings(**kwargs)


def _guard(tmp_path, **overrides):
    broker = FakeBroker()
    broker.connect()
    return RiskGuard(broker, _settings(tmp_path, **overrides))


def _stock_order(symbol="AAPL", action="BUY", qty=10, price=100.0):
    return OrderRequest(contract=Contract(symbol=symbol), action=action, quantity=qty, limit_price=price)


def _ctx(**overrides):
    kwargs = dict(nav=100_000.0)
    kwargs.update(overrides)
    return GuardContext(**kwargs)


def test_ok_order_passes_and_is_placed(tmp_path):
    guard = _guard(tmp_path)
    order = _stock_order()
    status = guard.place_order(order, _ctx(is_new_position=True, open_positions=1))
    assert status.status == "filled"
    assert guard.broker.positions()[0].symbol == "AAPL"


def test_kill_switch_file_blocks_orders(tmp_path):
    guard = _guard(tmp_path)
    (tmp_path / "KILL").touch()
    with pytest.raises(GuardRejection, match="kill switch"):
        guard.place_order(_stock_order(), _ctx())


def test_engage_kill_switch_cancels_all_and_blocks(tmp_path):
    guard = _guard(tmp_path)
    assert not guard.kill_switch_active
    guard.engage_kill_switch("manual stop")
    assert guard.kill_switch_active
    with pytest.raises(GuardRejection, match="kill switch"):
        guard.place_order(_stock_order(), _ctx())


def test_reset_kill_switch_allows_orders_again(tmp_path):
    guard = _guard(tmp_path)
    guard.engage_kill_switch("test")
    guard.reset_kill_switch()
    assert not guard.kill_switch_active
    status = guard.place_order(_stock_order(), _ctx(is_new_position=True))
    assert status.status == "filled"


def test_live_without_confirm_is_read_only(tmp_path):
    guard = _guard(tmp_path, trading_mode=TradingMode.LIVE, live_confirm="")
    with pytest.raises(GuardRejection, match="read-only"):
        guard.place_order(_stock_order(), _ctx())


def test_live_with_correct_confirm_is_authorized(tmp_path):
    guard = _guard(tmp_path, trading_mode=TradingMode.LIVE, live_confirm=LIVE_CONFIRM_PHRASE)
    status = guard.place_order(_stock_order(), _ctx(is_new_position=True))
    assert status.status == "filled"


def test_market_order_on_option_rejected(tmp_path):
    guard = _guard(tmp_path)
    contract = Contract(symbol="AAPL", sec_type="OPT", right="P", strike=100, expiry="20261218")
    order = OrderRequest(contract=contract, action="BUY", quantity=1, order_type="MKT")
    with pytest.raises(GuardRejection, match="market orders on options"):
        guard.place_order(order, _ctx())


def test_naked_short_call_rejected(tmp_path):
    guard = _guard(tmp_path)
    contract = Contract(symbol="AAPL", sec_type="OPT", right="C", strike=200, expiry="20261218")
    order = OrderRequest(contract=contract, action="SELL", quantity=1, limit_price=2.0)
    with pytest.raises(GuardRejection, match="naked short calls"):
        guard.place_order(order, _ctx(underlying_shares_held=0))


def test_covered_call_allowed(tmp_path):
    guard = _guard(tmp_path)
    contract = Contract(symbol="AAPL", sec_type="OPT", right="C", strike=200, expiry="20261218")
    order = OrderRequest(contract=contract, action="SELL", quantity=1, limit_price=2.0)
    status = guard.place_order(order, _ctx(underlying_shares_held=100))
    assert status.status == "filled"


def test_bag_short_call_without_matching_long_call_rejected(tmp_path):
    guard = _guard(tmp_path)
    short_leg = Contract(symbol="AAPL", sec_type="OPT", right="C", con_id=1, leg_action="SELL", leg_ratio=1)
    put_leg = Contract(symbol="AAPL", sec_type="OPT", right="P", con_id=2, leg_action="BUY", leg_ratio=1)
    bag = Contract(symbol="AAPL", sec_type="BAG", legs=[short_leg, put_leg])
    order = OrderRequest(contract=bag, action="BUY", quantity=1, limit_price=1.0)
    with pytest.raises(GuardRejection, match="naked short calls"):
        guard.place_order(order, _ctx())


def test_bag_call_credit_spread_allowed(tmp_path):
    guard = _guard(tmp_path)
    short_leg = Contract(symbol="AAPL", sec_type="OPT", right="C", con_id=1, leg_action="SELL", leg_ratio=1)
    long_leg = Contract(symbol="AAPL", sec_type="OPT", right="C", con_id=2, leg_action="BUY", leg_ratio=1)
    bag = Contract(symbol="AAPL", sec_type="BAG", legs=[short_leg, long_leg])
    order = OrderRequest(contract=bag, action="SELL", quantity=1, limit_price=1.0)
    status = guard.place_order(order, _ctx())
    assert status.status == "filled"


def test_max_options_contracts_per_order(tmp_path):
    guard = _guard(tmp_path, max_options_contracts_per_order=10)
    contract = Contract(symbol="AAPL", sec_type="OPT", right="P", strike=100, expiry="20261218")
    order = OrderRequest(contract=contract, action="BUY", quantity=11, limit_price=1.0)
    with pytest.raises(GuardRejection, match="max_options_contracts_per_order"):
        guard.place_order(order, _ctx())


def test_max_order_notional(tmp_path):
    guard = _guard(tmp_path, max_order_notional=1_000)
    order = _stock_order(qty=100, price=100.0)  # notional 10,000
    with pytest.raises(GuardRejection, match="max_order_notional"):
        guard.place_order(order, _ctx())


def test_max_position_pct_nav(tmp_path):
    guard = _guard(tmp_path, max_position_pct_nav=0.10, max_order_notional=1_000_000)
    order = _stock_order(qty=200, price=100.0)  # 20,000 notional on 100k NAV = 20%
    with pytest.raises(GuardRejection, match="max_position_pct_nav"):
        guard.place_order(order, _ctx(nav=100_000.0))


def test_max_open_positions_only_blocks_new_symbols(tmp_path):
    guard = _guard(tmp_path, max_open_positions=2)
    ctx_full = _ctx(open_positions=2, is_new_position=True)
    with pytest.raises(GuardRejection, match="max_open_positions"):
        guard.place_order(_stock_order(symbol="MSFT"), ctx_full)
    # adding to an existing position doesn't count as opening a new one
    ctx_existing = _ctx(open_positions=2, is_new_position=False)
    status = guard.place_order(_stock_order(symbol="AAPL"), ctx_existing)
    assert status.status == "filled"


def test_max_daily_loss_blocks_new_orders(tmp_path):
    guard = _guard(tmp_path, max_daily_loss_pct_nav=0.02)
    ctx = _ctx(nav=100_000.0, day_realized_pnl=-2_500.0)  # -2.5%
    with pytest.raises(GuardRejection, match="max_daily_loss_pct_nav"):
        guard.place_order(_stock_order(), ctx)


def test_pdt_blocks_fourth_day_trade_under_25k(tmp_path):
    guard = _guard(tmp_path)
    ctx = _ctx(nav=10_000.0, is_day_trade=True, day_trades_count=3)
    with pytest.raises(GuardRejection, match="PDT"):
        guard.place_order(_stock_order(), ctx)


def test_pdt_allows_over_25k_nav(tmp_path):
    guard = _guard(tmp_path)
    ctx = _ctx(nav=30_000.0, is_day_trade=True, day_trades_count=5, is_new_position=True)
    status = guard.place_order(_stock_order(), ctx)
    assert status.status == "filled"


def test_config_cannot_loosen_naked_calls_or_market_options():
    with pytest.raises(ValueError):
        Settings(allow_naked_short_calls=True)
    with pytest.raises(ValueError):
        Settings(allow_market_orders_options=True)


def test_fixed_fractional_size_respects_risk_and_caps():
    settings = Settings(max_order_notional=1_000_000, max_position_pct_nav=0.5)
    qty = fixed_fractional_size(
        nav=100_000, risk_pct=0.01, entry_price=50.0, stop_price=45.0, settings=settings
    )
    # risking 1% of 100k = 1000, risk per share = 5 -> 200 shares
    assert qty == 200


def test_fixed_fractional_size_capped_by_notional():
    settings = Settings(max_order_notional=1_000, max_position_pct_nav=0.5)
    qty = fixed_fractional_size(
        nav=100_000, risk_pct=0.5, entry_price=50.0, stop_price=45.0, settings=settings
    )
    assert qty * 50.0 <= 1_000


def test_atr_stop_price_directions():
    assert atr_stop_price(100.0, atr=2.0, atr_multiplier=2.0, direction="long") == 96.0
    assert atr_stop_price(100.0, atr=2.0, atr_multiplier=2.0, direction="short") == 104.0


def test_size_by_fixed_fractional_atr():
    settings = Settings(max_order_notional=1_000_000, max_position_pct_nav=0.5)
    qty = size_by_fixed_fractional_atr(
        nav=100_000, risk_pct=0.01, entry_price=50.0, atr=2.5, atr_multiplier=2.0, settings=settings
    )
    # stop = 50 - 5 = 45, risk per share 5 -> same as fixed_fractional test above
    assert qty == 200

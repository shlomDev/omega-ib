from omega_ib.broker.base import Contract, OrderRequest
from omega_ib.broker.fake import FakeBroker


def test_connect_disconnect():
    b = FakeBroker()
    assert not b.is_connected
    b.connect()
    assert b.is_connected
    b.disconnect()
    assert not b.is_connected


def test_buy_creates_position_and_reduces_cash():
    b = FakeBroker(starting_nav=100_000.0)
    b.connect()
    contract = b.qualify_contract(Contract(symbol="AAPL"))
    status = b.place_order(OrderRequest(contract=contract, action="BUY", quantity=10, limit_price=100.0))
    assert status.status == "filled"
    positions = b.positions()
    assert len(positions) == 1
    assert positions[0].symbol == "AAPL"
    assert positions[0].quantity == 10
    summary = b.account_summary()
    assert summary.nav == 100_000.0  # cash down, position value up, NAV unchanged at same price


def test_sell_closes_position_and_realizes_pnl():
    b = FakeBroker(starting_nav=100_000.0)
    b.connect()
    contract = b.qualify_contract(Contract(symbol="AAPL"))
    b.place_order(OrderRequest(contract=contract, action="BUY", quantity=10, limit_price=100.0))
    b.set_price("AAPL", 110.0)
    b.place_order(OrderRequest(contract=contract, action="SELL", quantity=10, limit_price=110.0))
    assert b.positions() == []
    summary = b.account_summary()
    assert summary.realized_pnl == 100.0
    assert summary.nav == 100_100.0


def test_cancel_order_and_cancel_all():
    b = FakeBroker()
    b.connect()
    contract = b.qualify_contract(Contract(symbol="AAPL"))
    status = b.place_order(OrderRequest(contract=contract, action="BUY", quantity=1, limit_price=1.0))
    # already filled -> cancel is a no-op
    b.cancel_order(status.order_id)
    assert b.open_orders() == []
    b.cancel_all()
    assert b.open_orders() == []

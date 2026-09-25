"""Unit tests for the pure ib_async <-> omega_ib conversion helpers.

No IB Gateway is used or required: these build ib_async objects directly in-process.
End-to-end connect/reconnect against a real paper Gateway is exercised by
omega_ib/tools/check_connection.py and is pending until run on a host with a Gateway.
"""

from ib_async import AccountValue, PortfolioItem, Trade
from ib_async.order import Order as IBOrder
from ib_async.order import OrderStatus as IBOrderStatus

from omega_ib.broker.base import Contract, OrderRequest
from omega_ib.broker.ib import (
    _parse_account_summary,
    _portfolio_item_to_position,
    _to_ib_contract,
    _to_ib_order,
    _trade_to_status,
)


def test_to_ib_contract_stock():
    c = _to_ib_contract(Contract(symbol="AAPL"))
    assert c.symbol == "AAPL"
    assert c.secType == "STK"
    assert c.exchange == "SMART"


def test_to_ib_contract_option():
    c = _to_ib_contract(
        Contract(symbol="AAPL", sec_type="OPT", expiry="20261218", strike=200.0, right="C")
    )
    assert c.secType == "OPT"
    assert c.strike == 200.0
    assert c.right == "C"


def test_to_ib_contract_bag_combo_legs():
    leg1 = Contract(symbol="AAPL", sec_type="OPT", con_id=111, leg_action="BUY", leg_ratio=1)
    leg2 = Contract(symbol="AAPL", sec_type="OPT", con_id=222, leg_action="SELL", leg_ratio=1)
    bag = _to_ib_contract(Contract(symbol="AAPL", sec_type="BAG", legs=[leg1, leg2]))
    assert bag.secType == "BAG"
    assert len(bag.comboLegs) == 2
    assert bag.comboLegs[0].conId == 111
    assert bag.comboLegs[0].action == "BUY"
    assert bag.comboLegs[1].action == "SELL"


def test_to_ib_contract_bag_requires_legs():
    import pytest

    with pytest.raises(ValueError):
        _to_ib_contract(Contract(symbol="AAPL", sec_type="BAG", legs=[]))


def test_to_ib_order_limit():
    req = OrderRequest(contract=Contract(symbol="AAPL"), action="BUY", quantity=10, limit_price=150.0)
    ib_order = _to_ib_order(req)
    assert isinstance(ib_order, IBOrder)
    assert ib_order.action == "BUY"
    assert ib_order.totalQuantity == 10
    assert ib_order.orderType == "LMT"
    assert ib_order.lmtPrice == 150.0


def test_to_ib_order_market_rejected_only_by_config_not_here():
    # options_builder/execution layers enforce "no market orders on options" (CLAUDE.md rule 4);
    # the broker layer itself is mechanical and will build whatever OrderRequest it's given.
    req = OrderRequest(contract=Contract(symbol="AAPL"), action="SELL", quantity=5, order_type="MKT")
    ib_order = _to_ib_order(req)
    assert ib_order.orderType == "MKT"


def test_to_ib_order_missing_limit_price_raises():
    import pytest

    req = OrderRequest(contract=Contract(symbol="AAPL"), action="BUY", quantity=1, order_type="LMT")
    with pytest.raises(ValueError):
        _to_ib_order(req)


def test_parse_account_summary():
    rows = [
        AccountValue(account="U123", tag="NetLiquidation", value="100000.0", currency="USD", modelCode=""),
        AccountValue(account="U123", tag="TotalCashValue", value="50000.0", currency="USD", modelCode=""),
        AccountValue(account="U123", tag="BuyingPower", value="200000.0", currency="USD", modelCode=""),
        AccountValue(account="U123", tag="UnrealizedPnL", value="1200.0", currency="USD", modelCode=""),
        AccountValue(account="U123", tag="RealizedPnL", value="-300.0", currency="USD", modelCode=""),
        AccountValue(account="U123", tag="ExchangeRate", value="1.0", currency="USD", modelCode=""),
    ]
    summary = _parse_account_summary(rows)
    assert summary.nav == 100000.0
    assert summary.cash == 50000.0
    assert summary.buying_power == 200000.0
    assert summary.unrealized_pnl == 1200.0
    assert summary.realized_pnl == -300.0
    assert summary.day_pnl == 900.0


def test_portfolio_item_to_position():
    from ib_async.contract import Stock

    item = PortfolioItem(
        contract=Stock("AAPL", "SMART", "USD"),
        position=10.0,
        marketPrice=155.0,
        marketValue=1550.0,
        averageCost=150.0,
        unrealizedPNL=50.0,
        realizedPNL=0.0,
        account="U123",
    )
    pos = _portfolio_item_to_position(item)
    assert pos.symbol == "AAPL"
    assert pos.quantity == 10.0
    assert pos.avg_cost == 150.0
    assert pos.market_price == 155.0
    assert pos.unrealized_pnl == 50.0


def test_trade_to_status():
    ib_order = IBOrder(orderId=42, action="BUY", totalQuantity=10, orderType="LMT", lmtPrice=100.0)
    trade = Trade(
        contract=None,
        order=ib_order,
        orderStatus=IBOrderStatus(orderId=42, status="Filled", filled=10, remaining=0, avgFillPrice=100.5),
    )
    status = _trade_to_status(trade)
    assert status.order_id == "42"
    assert status.status == "filled"
    assert status.filled == 10
    assert status.avg_fill_price == 100.5

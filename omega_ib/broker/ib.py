"""Real IB Gateway broker via ib_async. Connect/reconnect/heartbeat/orders/positions/PnL.

No IB Gateway is reachable in this dev/CI sandbox, so the pure conversion helpers
(`_to_ib_contract`, `_to_ib_order`, `_parse_account_summary`, `_portfolio_item_to_position`,
`_trade_to_status`) are unit tested directly against ib_async objects built in-process
(no network). End-to-end behavior against a live paper Gateway is exercised by
`omega_ib/tools/check_connection.py` and is tracked as pending in PROGRESS.md until
run on a host with IB Gateway reachable.
"""

from __future__ import annotations

import logging
import time

from ib_async import IB, AccountValue, LimitOrder, MarketOrder, PortfolioItem, StopOrder, Trade
from ib_async import Contract as IBContract
from ib_async.contract import Bag, ComboLeg, Option, Stock

from omega_ib.broker.base import (
    AccountSummary,
    BrokerBase,
    Contract,
    OrderRequest,
    OrderStatus,
    Position,
)

logger = logging.getLogger(__name__)

_ACCOUNT_TAGS = {"NetLiquidation", "TotalCashValue", "BuyingPower", "UnrealizedPnL", "RealizedPnL"}


def _to_ib_contract(contract: Contract) -> IBContract:
    if contract.sec_type == "STK":
        return Stock(contract.symbol, contract.exchange, contract.currency)
    if contract.sec_type == "OPT":
        return Option(
            contract.symbol,
            contract.expiry,
            contract.strike,
            contract.right,
            contract.exchange,
            currency=contract.currency,
        )
    if contract.sec_type == "BAG":
        if not contract.legs:
            raise ValueError("BAG contract requires at least one leg")
        bag = Bag()
        bag.symbol = contract.symbol
        bag.exchange = contract.exchange
        bag.currency = contract.currency
        bag.comboLegs = [
            ComboLeg(conId=leg.con_id, ratio=leg.leg_ratio, action=leg.leg_action, exchange=leg.exchange)
            for leg in contract.legs
        ]
        return bag
    raise ValueError(f"unsupported sec_type: {contract.sec_type}")


def _to_ib_order(order: OrderRequest):
    if order.order_type == "LMT":
        if order.limit_price is None:
            raise ValueError("LMT order requires limit_price")
        ib_order = LimitOrder(order.action, order.quantity, order.limit_price)
    elif order.order_type == "STP":
        if order.stop_price is None:
            raise ValueError("STP order requires stop_price")
        ib_order = StopOrder(order.action, order.quantity, order.stop_price)
    elif order.order_type == "MKT":
        ib_order = MarketOrder(order.action, order.quantity)
    else:
        raise ValueError(f"unsupported order_type: {order.order_type}")
    ib_order.tif = order.tif
    ib_order.outsideRth = order.outside_rth
    ib_order.transmit = order.transmit
    if order.parent_id is not None:
        ib_order.parentId = int(order.parent_id)
    return ib_order


def _parse_account_summary(rows: list[AccountValue]) -> AccountSummary:
    values: dict[str, float] = {}
    for row in rows:
        if row.tag in _ACCOUNT_TAGS and row.currency in ("USD", "BASE", ""):
            try:
                values[row.tag] = float(row.value)
            except ValueError:
                continue
    nav = values.get("NetLiquidation", 0.0)
    cash = values.get("TotalCashValue", 0.0)
    unrealized = values.get("UnrealizedPnL", 0.0)
    realized = values.get("RealizedPnL", 0.0)
    return AccountSummary(
        nav=nav,
        cash=cash,
        buying_power=values.get("BuyingPower", 0.0),
        day_pnl=unrealized + realized,
        unrealized_pnl=unrealized,
        realized_pnl=realized,
    )


def _portfolio_item_to_position(item: PortfolioItem) -> Position:
    return Position(
        symbol=item.contract.symbol,
        sec_type=item.contract.secType,
        quantity=item.position,
        avg_cost=item.averageCost,
        market_price=item.marketPrice,
        unrealized_pnl=item.unrealizedPNL,
    )


def _trade_to_status(trade: Trade) -> OrderStatus:
    status = trade.orderStatus
    return OrderStatus(
        order_id=str(trade.order.orderId),
        status=status.status.lower() if status.status else "unknown",
        filled=status.filled,
        remaining=status.remaining,
        avg_fill_price=status.avgFillPrice or 0.0,
    )


class IBBroker(BrokerBase):
    """Broker backed by a real IB Gateway connection (paper or live per config.py)."""

    def __init__(self, host: str, port: int, client_id: int) -> None:
        self.ib = IB()
        self._host = host
        self._port = port
        self._client_id = client_id
        self.ib.disconnectedEvent += self._on_disconnected
        self.ib.errorEvent += self._on_error

    def _on_disconnected(self) -> None:
        logger.warning("IB Gateway disconnected")

    def _on_error(self, reqId: int, errorCode: int, errorString: str, contract) -> None:
        logger.error("IB error %s (reqId=%s): %s", errorCode, reqId, errorString)

    def connect(self) -> None:
        self.ib.connect(self._host, self._port, clientId=self._client_id, readonly=False)

    def disconnect(self) -> None:
        self.ib.disconnect()

    @property
    def is_connected(self) -> bool:
        return self.ib.isConnected()

    def reconnect_with_backoff(self, max_attempts: int = 5, base_delay: float = 2.0) -> bool:
        """Exponential backoff reconnect. Returns True once connected."""
        for attempt in range(1, max_attempts + 1):
            try:
                self.connect()
                return True
            except Exception as exc:  # noqa: BLE001 - reconnect loop must not raise
                delay = base_delay * (2 ** (attempt - 1))
                logger.warning("reconnect attempt %d/%d failed: %s (retry in %.1fs)", attempt, max_attempts, exc, delay)
                if attempt < max_attempts:
                    time.sleep(delay)
        return False

    def heartbeat(self) -> bool:
        """Cheap liveness check. Returns False (without raising) if the Gateway is unresponsive."""
        try:
            self.ib.reqCurrentTime()
            return True
        except Exception:  # noqa: BLE001
            return False

    def qualify_contract(self, contract: Contract) -> Contract:
        ib_contract = _to_ib_contract(contract)
        qualified = self.ib.qualifyContracts(ib_contract)
        if not qualified:
            raise ValueError(f"could not qualify contract: {contract}")
        contract.con_id = qualified[0].conId
        return contract

    def place_order(self, order: OrderRequest) -> OrderStatus:
        ib_contract = _to_ib_contract(order.contract)
        ib_order = _to_ib_order(order)
        trade = self.ib.placeOrder(ib_contract, ib_order)
        self.ib.sleep(0)
        return _trade_to_status(trade)

    def cancel_order(self, order_id: str) -> None:
        for trade in self.ib.openTrades():
            if str(trade.order.orderId) == str(order_id):
                self.ib.cancelOrder(trade.order)
                return

    def cancel_all(self) -> None:
        self.ib.reqGlobalCancel()

    def positions(self) -> list[Position]:
        return [_portfolio_item_to_position(item) for item in self.ib.portfolio()]

    def account_summary(self) -> AccountSummary:
        return _parse_account_summary(self.ib.accountSummary())

    def open_orders(self) -> list[OrderStatus]:
        return [_trade_to_status(t) for t in self.ib.openTrades()]

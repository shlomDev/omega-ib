"""In-memory fake broker for tests and dry-run. No network, no IB Gateway required."""

from __future__ import annotations

import itertools

from omega_ib.broker.base import (
    AccountSummary,
    BrokerBase,
    Contract,
    OrderRequest,
    OrderStatus,
    Position,
)


class FakeBroker(BrokerBase):
    def __init__(self, starting_nav: float = 100_000.0) -> None:
        self._connected = False
        self._nav = starting_nav
        self._cash = starting_nav
        self._positions: dict[str, Position] = {}
        self._orders: dict[str, OrderStatus] = {}
        self._order_requests: dict[str, OrderRequest] = {}
        self._id_counter = itertools.count(1)
        self.day_pnl = 0.0
        self.realized_pnl = 0.0
        # Price book: symbol -> last price, settable by tests to simulate fills/market moves.
        self.prices: dict[str, float] = {}

    def connect(self) -> None:
        self._connected = True

    def disconnect(self) -> None:
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected

    def qualify_contract(self, contract: Contract) -> Contract:
        contract.con_id = contract.con_id or hash(contract.symbol) % 1_000_000
        return contract

    def set_price(self, symbol: str, price: float) -> None:
        self.prices[symbol] = price
        pos = self._positions.get(symbol)
        if pos:
            pos.market_price = price
            pos.unrealized_pnl = (price - pos.avg_cost) * pos.quantity

    def place_order(self, order: OrderRequest) -> OrderStatus:
        order_id = str(next(self._id_counter))
        price = order.limit_price or self.prices.get(order.contract.symbol, 0.0) or 0.0
        status = OrderStatus(
            order_id=order_id,
            status="filled",
            filled=order.quantity,
            remaining=0.0,
            avg_fill_price=price,
        )
        self._orders[order_id] = status
        self._order_requests[order_id] = order
        self._apply_fill(order, price)
        return status

    def _apply_fill(self, order: OrderRequest, price: float) -> None:
        symbol = order.contract.symbol
        signed_qty = order.quantity if order.action == "BUY" else -order.quantity
        pos = self._positions.get(symbol)
        notional = price * order.quantity
        if order.action == "BUY":
            self._cash -= notional
        else:
            self._cash += notional
        if pos is None:
            self._positions[symbol] = Position(
                symbol=symbol,
                sec_type=order.contract.sec_type,
                quantity=signed_qty,
                avg_cost=price,
                market_price=price,
            )
            return
        new_qty = pos.quantity + signed_qty
        if pos.quantity != 0 and (pos.quantity > 0) != (signed_qty > 0):
            closed_qty = min(abs(signed_qty), abs(pos.quantity))
            self.realized_pnl += (price - pos.avg_cost) * closed_qty * (1 if pos.quantity > 0 else -1)
        if new_qty == 0:
            del self._positions[symbol]
            return
        if (pos.quantity >= 0) == (signed_qty >= 0):
            pos.avg_cost = (pos.avg_cost * pos.quantity + price * signed_qty) / new_qty
        pos.quantity = new_qty
        pos.market_price = price

    def cancel_order(self, order_id: str) -> None:
        status = self._orders.get(order_id)
        if status and status.status not in ("filled", "cancelled"):
            status.status = "cancelled"
            status.remaining = 0.0

    def cancel_all(self) -> None:
        for status in self._orders.values():
            if status.status not in ("filled", "cancelled"):
                status.status = "cancelled"
                status.remaining = 0.0

    def positions(self) -> list[Position]:
        return list(self._positions.values())

    def account_summary(self) -> AccountSummary:
        unrealized = sum(p.unrealized_pnl for p in self._positions.values())
        equity = self._cash + sum(p.market_price * p.quantity for p in self._positions.values())
        return AccountSummary(
            nav=equity,
            cash=self._cash,
            buying_power=self._cash,
            day_pnl=self.realized_pnl + unrealized,
            unrealized_pnl=unrealized,
            realized_pnl=self.realized_pnl,
        )

    def open_orders(self) -> list[OrderStatus]:
        return [s for s in self._orders.values() if s.status not in ("filled", "cancelled")]

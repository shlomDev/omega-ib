"""In-memory fake broker for tests and dry-run. No network, no IB Gateway required.

Every order fills immediately at its limit price (or the mock price set via
set_price) -- *except* a bracket child order (stop or target, identified by
having `parent_id` set by execution/engine.py's build_bracket_order/
place_bracket_order). Those are held pending until set_price crosses their
trigger, at which point they fill and their OCA sibling is cancelled. Without
this, a bracket's entry + stop + target would all fill on the same call and
net out to a nonsensical position -- there is no real order book here to make
a STP/LMT child order wait for the market on its own.
"""

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
        # Bracket child orders (parent_id set) waiting for set_price to cross their trigger.
        self._pending_children: dict[str, OrderRequest] = {}

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
        self._check_pending_children(symbol, price)

    def place_order(self, order: OrderRequest) -> OrderStatus:
        order_id = str(next(self._id_counter))
        self._order_requests[order_id] = order
        if order.parent_id is not None:
            # Bracket child (stop/target): held pending until set_price triggers it.
            status = OrderStatus(order_id=order_id, status="submitted", filled=0.0, remaining=order.quantity)
            self._orders[order_id] = status
            self._pending_children[order_id] = order
            return status
        price = order.limit_price or self.prices.get(order.contract.symbol, 0.0) or 0.0
        status = OrderStatus(
            order_id=order_id,
            status="filled",
            filled=order.quantity,
            remaining=0.0,
            avg_fill_price=price,
        )
        self._orders[order_id] = status
        self._apply_fill(order, price)
        return status

    def _check_pending_children(self, symbol: str, price: float) -> None:
        for order_id, order in list(self._pending_children.items()):
            if order.contract.symbol != symbol:
                continue
            if order.order_type == "STP":
                triggered = price <= order.stop_price if order.action == "SELL" else price >= order.stop_price
            elif order.order_type == "LMT":
                triggered = price >= order.limit_price if order.action == "SELL" else price <= order.limit_price
            else:
                triggered = False
            if triggered:
                self._fill_pending_child(order_id, order, price)

    def _fill_pending_child(self, order_id: str, order: OrderRequest, price: float) -> None:
        del self._pending_children[order_id]
        status = self._orders[order_id]
        status.status = "filled"
        status.filled = order.quantity
        status.remaining = 0.0
        status.avg_fill_price = price
        self._apply_fill(order, price)
        for other_id, other_order in list(self._pending_children.items()):
            if other_order.parent_id == order.parent_id and other_id != order_id:
                del self._pending_children[other_id]
                other_status = self._orders[other_id]
                other_status.status = "cancelled"
                other_status.remaining = 0.0

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
        self._pending_children.pop(order_id, None)

    def cancel_all(self) -> None:
        for status in self._orders.values():
            if status.status not in ("filled", "cancelled"):
                status.status = "cancelled"
                status.remaining = 0.0
        self._pending_children.clear()

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

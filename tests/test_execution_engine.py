import itertools

from omega_ib.broker.base import AccountSummary, BrokerBase, Contract, OrderRequest, OrderStatus, Position
from omega_ib.broker.fake import FakeBroker
from omega_ib.config import Settings
from omega_ib.execution.engine import (
    FillTracker,
    build_bracket_order,
    place_bracket_order,
    submit_with_price_walk,
)
from omega_ib.risk.guard import GuardContext, RiskGuard


def _guard(tmp_path, broker):
    settings = Settings(kill_switch_file=str(tmp_path / "KILL"))
    return RiskGuard(broker, settings)


def _ctx(**overrides):
    kwargs = dict(nav=100_000.0, is_new_position=True)
    kwargs.update(overrides)
    return GuardContext(**kwargs)


def test_build_bracket_order_shapes_legs():
    contract = Contract(symbol="AAPL")
    bracket = build_bracket_order(contract, "BUY", 10, entry_price=100.0, stop_price=95.0, target_price=110.0)
    assert bracket.entry.action == "BUY"
    assert bracket.stop.action == "SELL"
    assert bracket.stop.order_type == "STP"
    assert bracket.target.action == "SELL"
    assert bracket.target.order_type == "LMT"
    assert bracket.entry.transmit is False
    assert bracket.target.transmit is True


def test_place_bracket_order_links_children_and_fills(tmp_path):
    broker = FakeBroker()
    broker.connect()
    guard = _guard(tmp_path, broker)
    contract = Contract(symbol="AAPL")
    bracket = build_bracket_order(contract, "BUY", 10, entry_price=100.0, stop_price=95.0, target_price=110.0)
    result = place_bracket_order(guard, bracket, _ctx())
    assert result.entry_status.status == "filled"
    assert bracket.stop.parent_id == int(result.entry_status.order_id)
    assert bracket.target.parent_id == bracket.stop.parent_id


class _ScriptedBroker(BrokerBase):
    """Minimal broker stub that returns a scripted sequence of order statuses,
    used to exercise submit_with_price_walk's retry loop without FakeBroker's
    always-fills-immediately behavior."""

    def __init__(self, statuses: list[str]) -> None:
        self._statuses = iter(statuses)
        self._counter = itertools.count(1)
        self.cancelled: list[str] = []
        self.placed_prices: list[float] = []

    def connect(self) -> None:
        pass

    def disconnect(self) -> None:
        pass

    @property
    def is_connected(self) -> bool:
        return True

    def qualify_contract(self, contract):
        return contract

    def place_order(self, order: OrderRequest) -> OrderStatus:
        self.placed_prices.append(order.limit_price)
        order_id = str(next(self._counter))
        status = next(self._statuses, "filled")
        return OrderStatus(order_id=order_id, status=status, filled=order.quantity if status == "filled" else 0.0)

    def cancel_order(self, order_id: str) -> None:
        self.cancelled.append(order_id)

    def cancel_all(self) -> None:
        pass

    def positions(self) -> list[Position]:
        return []

    def account_summary(self) -> AccountSummary:
        return AccountSummary(nav=100_000.0, cash=100_000.0, buying_power=100_000.0)

    def open_orders(self) -> list[OrderStatus]:
        return []


def test_submit_with_price_walk_retries_until_filled(tmp_path):
    broker = _ScriptedBroker(statuses=["submitted", "submitted", "filled"])
    guard = _guard(tmp_path, broker)
    order = OrderRequest(contract=Contract(symbol="AAPL"), action="BUY", quantity=10, limit_price=100.0)
    status = submit_with_price_walk(guard, order, _ctx(), max_steps=5, step_increment=0.05)
    assert status.status == "filled"
    assert len(broker.cancelled) == 2
    assert broker.placed_prices == [100.0, 100.05, 100.1]


def test_submit_with_price_walk_gives_up_after_max_steps(tmp_path):
    broker = _ScriptedBroker(statuses=["submitted"] * 10)
    guard = _guard(tmp_path, broker)
    order = OrderRequest(contract=Contract(symbol="AAPL"), action="SELL", quantity=5, limit_price=50.0)
    status = submit_with_price_walk(guard, order, _ctx(), max_steps=3, step_increment=0.1)
    assert status.status == "submitted"
    assert len(broker.cancelled) == 3
    # SELL walks the price down toward the market
    assert broker.placed_prices == [50.0, 49.9, 49.8, 49.7]


def test_submit_with_price_walk_requires_limit_price(tmp_path):
    broker = FakeBroker()
    broker.connect()
    guard = _guard(tmp_path, broker)
    order = OrderRequest(contract=Contract(symbol="AAPL"), action="BUY", quantity=1, order_type="MKT")
    import pytest

    with pytest.raises(ValueError):
        submit_with_price_walk(guard, order, _ctx())


def test_fill_tracker_records_once():
    tracker = FillTracker()
    status = OrderStatus(order_id="1", status="filled", filled=10, avg_fill_price=100.0)
    record = tracker.record(status, "AAPL")
    assert record is not None
    assert record.quantity == 10
    # calling again with the same order_id doesn't double-record
    assert tracker.record(status, "AAPL") is None
    assert len(tracker.fills()) == 1


def test_fill_tracker_ignores_unfilled():
    tracker = FillTracker()
    status = OrderStatus(order_id="1", status="submitted", filled=0)
    assert tracker.record(status, "AAPL") is None
    assert tracker.fills() == []

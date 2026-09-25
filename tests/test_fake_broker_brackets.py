"""FakeBroker's bracket-child (parent_id) pending/trigger/OCA behavior."""

from omega_ib.broker.base import Contract
from omega_ib.broker.fake import FakeBroker
from omega_ib.execution.engine import build_bracket_order


def test_bracket_entry_fills_children_stay_pending():
    broker = FakeBroker(starting_nav=100_000.0)
    broker.connect()
    contract = Contract(symbol="AAPL")
    bracket = build_bracket_order(contract, "BUY", 10, entry_price=100.0, stop_price=95.0, target_price=110.0)

    entry_status = broker.place_order(bracket.entry)
    assert entry_status.status == "filled"
    bracket.stop.parent_id = int(entry_status.order_id)
    bracket.target.parent_id = int(entry_status.order_id)
    stop_status = broker.place_order(bracket.stop)
    target_status = broker.place_order(bracket.target)

    assert stop_status.status == "submitted"
    assert target_status.status == "submitted"
    assert len(broker.positions()) == 1
    assert broker.positions()[0].quantity == 10  # only the entry filled, not both exits


def test_bracket_target_triggers_and_cancels_stop():
    broker = FakeBroker(starting_nav=100_000.0)
    broker.connect()
    contract = Contract(symbol="AAPL")
    bracket = build_bracket_order(contract, "BUY", 10, entry_price=100.0, stop_price=95.0, target_price=110.0)
    entry_status = broker.place_order(bracket.entry)
    bracket.stop.parent_id = int(entry_status.order_id)
    bracket.target.parent_id = int(entry_status.order_id)
    broker.place_order(bracket.stop)
    broker.place_order(bracket.target)

    broker.set_price("AAPL", 111.0)  # crosses the target

    assert broker.positions() == []  # position closed
    open_ids = {s.status for s in broker.open_orders()}
    assert open_ids == set()  # both children resolved (one filled, one cancelled)


def test_bracket_stop_triggers_and_cancels_target():
    broker = FakeBroker(starting_nav=100_000.0)
    broker.connect()
    contract = Contract(symbol="AAPL")
    bracket = build_bracket_order(contract, "BUY", 10, entry_price=100.0, stop_price=95.0, target_price=110.0)
    entry_status = broker.place_order(bracket.entry)
    bracket.stop.parent_id = int(entry_status.order_id)
    bracket.target.parent_id = int(entry_status.order_id)
    stop_status = broker.place_order(bracket.stop)
    target_status = broker.place_order(bracket.target)

    broker.set_price("AAPL", 94.0)  # crosses the stop

    assert broker.positions() == []
    assert broker._orders[stop_status.order_id].status == "filled"
    assert broker._orders[target_status.order_id].status == "cancelled"


def test_cancel_order_removes_pending_child():
    broker = FakeBroker(starting_nav=100_000.0)
    broker.connect()
    contract = Contract(symbol="AAPL")
    bracket = build_bracket_order(contract, "BUY", 10, entry_price=100.0, stop_price=95.0, target_price=110.0)
    entry_status = broker.place_order(bracket.entry)
    bracket.stop.parent_id = int(entry_status.order_id)
    stop_status = broker.place_order(bracket.stop)

    broker.cancel_order(stop_status.order_id)
    broker.set_price("AAPL", 50.0)  # would have triggered the stop if still pending

    assert broker._orders[stop_status.order_id].status == "cancelled"
    assert len(broker.positions()) == 1  # position untouched, cancelled order never filled

"""Broker interface shared by broker/fake.py (tests + dry-run) and broker/ib.py (live/paper via IB).

CLAUDE.md rule 2: every order passes through risk/guard.py. Nothing else may call
`place_order` on a broker implementation -- this is enforced by a repo-wide grep test
in tests/test_guard_enforcement.py.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class Contract:
    symbol: str
    sec_type: str = "STK"  # STK / OPT / BAG
    exchange: str = "SMART"
    currency: str = "USD"
    expiry: str = ""  # OPT only, YYYYMMDD
    strike: float = 0.0  # OPT only
    right: str = ""  # OPT only: C/P
    con_id: int = 0
    legs: list[Contract] = field(default_factory=list)  # BAG only


@dataclass
class OrderRequest:
    contract: Contract
    action: str  # BUY / SELL
    quantity: float
    order_type: str = "LMT"  # LMT / STP / MKT
    limit_price: float | None = None
    stop_price: float | None = None
    tif: str = "DAY"
    outside_rth: bool = False
    parent_id: int | None = None
    transmit: bool = True


@dataclass
class OrderStatus:
    order_id: str
    status: str  # submitted / filled / cancelled / rejected
    filled: float = 0.0
    remaining: float = 0.0
    avg_fill_price: float = 0.0


@dataclass
class Position:
    symbol: str
    sec_type: str
    quantity: float
    avg_cost: float
    market_price: float = 0.0
    unrealized_pnl: float = 0.0


@dataclass
class AccountSummary:
    nav: float
    cash: float
    buying_power: float
    day_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0


class BrokerBase(ABC):
    """Minimal surface both the fake broker and the real IB broker implement."""

    @abstractmethod
    def connect(self) -> None: ...

    @abstractmethod
    def disconnect(self) -> None: ...

    @property
    @abstractmethod
    def is_connected(self) -> bool: ...

    @abstractmethod
    def qualify_contract(self, contract: Contract) -> Contract: ...

    @abstractmethod
    def place_order(self, order: OrderRequest) -> OrderStatus: ...

    @abstractmethod
    def cancel_order(self, order_id: str) -> None: ...

    @abstractmethod
    def cancel_all(self) -> None: ...

    @abstractmethod
    def positions(self) -> list[Position]: ...

    @abstractmethod
    def account_summary(self) -> AccountSummary: ...

    @abstractmethod
    def open_orders(self) -> list[OrderStatus]: ...

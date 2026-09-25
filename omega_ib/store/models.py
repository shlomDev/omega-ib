"""SQLAlchemy models for the audit-everything requirement in CLAUDE.md rule 7.

Every order, fill, signal, AI decision, and guard rejection must be persisted
with a reason. These models are the single source of truth for that log.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


class Base(DeclarativeBase):
    pass


class Signal(Base):
    __tablename__ = "signals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    symbol: Mapped[str] = mapped_column(String(32))
    strategy: Mapped[str] = mapped_column(String(64))
    direction: Mapped[str] = mapped_column(String(8))  # long/short
    score: Mapped[float] = mapped_column(Float, default=0.0)
    payload: Mapped[str] = mapped_column(Text, default="{}")  # JSON blob of signal detail

    orders: Mapped[list[Order]] = relationship(back_populates="signal")


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    broker_order_id: Mapped[str] = mapped_column(String(64), default="")
    symbol: Mapped[str] = mapped_column(String(32))
    asset_type: Mapped[str] = mapped_column(String(16))  # STK / OPT / BAG
    action: Mapped[str] = mapped_column(String(8))  # BUY/SELL
    quantity: Mapped[float] = mapped_column(Float)
    order_type: Mapped[str] = mapped_column(String(16))  # LMT/STP/MKT
    limit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    trading_mode: Mapped[str] = mapped_column(String(8), default="paper")
    signal_id: Mapped[int | None] = mapped_column(ForeignKey("signals.id"), nullable=True)

    signal: Mapped[Signal | None] = relationship(back_populates="orders")
    fills: Mapped[list[Fill]] = relationship(back_populates="order")


class Fill(Base):
    __tablename__ = "fills"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"))
    price: Mapped[float] = mapped_column(Float)
    quantity: Mapped[float] = mapped_column(Float)
    commission: Mapped[float] = mapped_column(Float, default=0.0)

    order: Mapped[Order] = relationship(back_populates="fills")


class Trade(Base):
    """A closed round-trip position, used for P&L / stats reporting."""

    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    opened_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    closed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    symbol: Mapped[str] = mapped_column(String(32))
    strategy: Mapped[str] = mapped_column(String(64))
    realized_pnl: Mapped[float | None] = mapped_column(Float, nullable=True)


class AIDecision(Base):
    __tablename__ = "ai_decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    kind: Mapped[str] = mapped_column(String(32))  # pre_market / mid_session / eod
    symbol: Mapped[str] = mapped_column(String(32), default="")
    action: Mapped[str] = mapped_column(String(32))  # propose/veto/tighten/no_action
    rationale: Mapped[str] = mapped_column(Text, default="")
    raw_response: Mapped[str] = mapped_column(Text, default="")


class AuditLog(Base):
    """Append-only record of every order, fill, signal, AI decision, and guard rejection."""

    __tablename__ = "audit"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    event_type: Mapped[str] = mapped_column(String(32))
    reason: Mapped[str] = mapped_column(Text)
    detail: Mapped[str] = mapped_column(Text, default="{}")  # JSON blob


class DailySnapshot(Base):
    __tablename__ = "daily_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    date: Mapped[dt.date] = mapped_column(DateTime(timezone=True), default=utcnow)
    nav: Mapped[float] = mapped_column(Float)
    realized_pnl: Mapped[float] = mapped_column(Float, default=0.0)
    unrealized_pnl: Mapped[float] = mapped_column(Float, default=0.0)
    open_positions: Mapped[int] = mapped_column(Integer, default=0)

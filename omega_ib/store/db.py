"""Engine/session factory + the append-only audit helper every module must use."""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from omega_ib.config import settings
from omega_ib.store.models import AuditLog, Base

_engine = None
_SessionLocal: sessionmaker | None = None


def init_db(database_url: str | None = None) -> None:
    global _engine, _SessionLocal
    url = database_url or settings.database_url
    is_memory_sqlite = url in ("sqlite://", "sqlite:///:memory:")
    kwargs = {}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    if is_memory_sqlite:
        kwargs["poolclass"] = StaticPool
    _engine = create_engine(url, **kwargs)
    Base.metadata.create_all(_engine)
    _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False)


def get_engine():
    if _engine is None:
        init_db()
    return _engine


@contextmanager
def session_scope() -> Iterator[Session]:
    if _SessionLocal is None:
        init_db()
    assert _SessionLocal is not None
    session = _SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def write_audit(event_type: str, reason: str, detail: dict | None = None) -> None:
    """Append-only audit trail entry. CLAUDE.md rule 7: every decision gets a reason."""
    with session_scope() as session:
        session.add(AuditLog(event_type=event_type, reason=reason, detail=json.dumps(detail or {})))

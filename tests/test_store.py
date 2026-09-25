import json

from omega_ib.store.db import session_scope, write_audit
from omega_ib.store.models import AuditLog, Signal


def test_write_audit_persists_reason():
    write_audit("guard_rejection", "max_position_pct_nav exceeded", {"symbol": "AAPL"})
    with session_scope() as session:
        rows = session.query(AuditLog).all()
        assert len(rows) == 1
        assert rows[0].event_type == "guard_rejection"
        assert rows[0].reason == "max_position_pct_nav exceeded"
        assert json.loads(rows[0].detail) == {"symbol": "AAPL"}


def test_signal_roundtrip():
    with session_scope() as session:
        session.add(Signal(symbol="AAPL", strategy="momentum_breakout", direction="long", score=0.8))
    with session_scope() as session:
        sig = session.query(Signal).filter_by(symbol="AAPL").one()
        assert sig.strategy == "momentum_breakout"
        assert sig.score == 0.8

"""CLAUDE.md rule 2: nothing but risk/guard.py may call broker.place_order.

This greps the whole omega_ib package (production code, not tests) for calls
matching `broker.place_order(` (any receiver expression ending in "broker", e.g.
`self.broker.place_order(`, `app.state.broker.place_order(`) and fails if any
file other than risk/guard.py contains one. Calling the *guard's* own
`place_order` (e.g. `guard.place_order(...)` from execution/engine.py) is the
sanctioned path and is not flagged. Function/method *definitions* of
place_order (the broker implementations) are allowed everywhere, since
defining the method isn't calling it.
"""

import re
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1] / "omega_ib"
ALLOWED_CALLER = PACKAGE_ROOT / "risk" / "guard.py"

CALL_PATTERN = re.compile(r"\bbroker\.place_order\(")
DEF_PATTERN = re.compile(r"^\s*(async )?def place_order\b")


def test_only_guard_calls_broker_place_order():
    violations = []
    for path in PACKAGE_ROOT.rglob("*.py"):
        text = path.read_text()
        for lineno, line in enumerate(text.splitlines(), start=1):
            if DEF_PATTERN.match(line):
                continue
            if CALL_PATTERN.search(line) and path != ALLOWED_CALLER:
                violations.append(f"{path.relative_to(PACKAGE_ROOT.parent)}:{lineno}: {line.strip()}")
    assert not violations, "only risk/guard.py may call broker.place_order:\n" + "\n".join(violations)


def test_guard_module_actually_calls_place_order():
    """Sanity check that the allowlisted file really does call it (test isn't vacuous)."""
    text = ALLOWED_CALLER.read_text()
    assert CALL_PATTERN.search(text)

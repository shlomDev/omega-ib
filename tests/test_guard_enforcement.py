"""CLAUDE.md rule 2: nothing but risk/guard.py may call broker.place_order.

This greps the whole omega_ib package (production code, not tests) for calls to
`.place_order(` and fails if any file other than risk/guard.py contains one.
Function/method *definitions* of place_order (the broker implementations) are
allowed everywhere, since defining the method isn't calling it.
"""

from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1] / "omega_ib"
ALLOWED_CALLER = PACKAGE_ROOT / "risk" / "guard.py"


def test_only_guard_calls_broker_place_order():
    violations = []
    for path in PACKAGE_ROOT.rglob("*.py"):
        text = path.read_text()
        for lineno, line in enumerate(text.splitlines(), start=1):
            stripped = line.strip()
            if stripped.startswith("def place_order") or stripped.startswith("async def place_order"):
                continue
            if ".place_order(" in line and path != ALLOWED_CALLER:
                violations.append(f"{path.relative_to(PACKAGE_ROOT.parent)}:{lineno}: {stripped}")
    assert not violations, "only risk/guard.py may call broker.place_order:\n" + "\n".join(violations)


def test_guard_module_actually_calls_place_order():
    """Sanity check that the allowlisted file really does call it (test isn't vacuous)."""
    text = ALLOWED_CALLER.read_text()
    assert "self.broker.place_order(" in text

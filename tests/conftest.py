import os

os.environ.setdefault("TRADING_MODE", "paper")
os.environ.setdefault("WEB_AUTH_TOKEN", "test-token")
os.environ.setdefault("DATABASE_URL", "sqlite://")

import pytest

from omega_ib.store import db as db_module


@pytest.fixture(autouse=True)
def _fresh_db():
    """Every test gets a clean in-memory SQLite database."""
    db_module.init_db("sqlite://")
    yield

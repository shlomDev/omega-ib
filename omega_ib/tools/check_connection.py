"""Read-only sanity check: connect to IB Gateway, print account summary + positions, disconnect.

Usage:
    python -m omega_ib.tools.check_connection

Requires a reachable IB Gateway (paper by default per config.py). This script
never places orders -- it is a connectivity/read-only smoke test only.
"""

from __future__ import annotations

import logging
import sys

from omega_ib.broker.ib import IBBroker
from omega_ib.config import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("check_connection")


def main() -> int:
    logger.info(
        "connecting to IB Gateway at %s:%s (clientId=%s, mode=%s)",
        settings.ib_host,
        settings.ib_port,
        settings.ib_client_id,
        settings.trading_mode,
    )
    broker = IBBroker(settings.ib_host, settings.ib_port, settings.ib_client_id)
    try:
        broker.connect()
    except Exception as exc:  # noqa: BLE001
        logger.error("connection failed: %s", exc)
        return 1

    try:
        if not broker.heartbeat():
            logger.error("heartbeat failed after connect")
            return 1
        summary = broker.account_summary()
        logger.info("account summary: %s", summary)
        positions = broker.positions()
        logger.info("open positions: %d", len(positions))
        for pos in positions:
            logger.info("  %s qty=%s avg_cost=%s market_price=%s", pos.symbol, pos.quantity, pos.avg_cost, pos.market_price)
        open_orders = broker.open_orders()
        logger.info("open orders: %d", len(open_orders))
        return 0
    finally:
        broker.disconnect()


if __name__ == "__main__":
    sys.exit(main())

"""Telegram alerts + bot commands: /status /pnl /positions /risk /scan /opts /kill /resume.

Real Telegram API calls require TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID and are not
exercised in tests/CI (no network). `send_alert` degrades to a log line when
unconfigured so the rest of the system keeps working. The message-formatting
functions and `handle_command`'s dispatch logic are pure and fully unit tested;
`/kill` and `/resume` go through risk/guard.py exactly like the Web UI button
(CLAUDE.md rule 3: kill switch is reachable from Telegram + UI + the KILL file).
"""

from __future__ import annotations

import logging

import httpx

from omega_ib.broker.base import AccountSummary, BrokerBase, Position
from omega_ib.config import Settings
from omega_ib.config import settings as default_settings
from omega_ib.risk.guard import RiskGuard

logger = logging.getLogger(__name__)


def format_status(summary: AccountSummary, kill_switch_active: bool, trading_mode: str) -> str:
    return (
        "OMEGA-IB status\n"
        f"Mode: {trading_mode}\n"
        f"NAV: ${summary.nav:,.2f}\n"
        f"Day P&L: ${summary.day_pnl:,.2f}\n"
        f"Kill switch: {'ENGAGED' if kill_switch_active else 'off'}"
    )


def format_pnl(summary: AccountSummary) -> str:
    return (
        f"Day P&L: ${summary.day_pnl:,.2f}\n"
        f"Unrealized: ${summary.unrealized_pnl:,.2f}\n"
        f"Realized: ${summary.realized_pnl:,.2f}"
    )


def format_positions(positions: list[Position]) -> str:
    if not positions:
        return "No open positions."
    lines = [f"{p.symbol}: {p.quantity:g} @ {p.avg_cost:.2f} (P&L ${p.unrealized_pnl:,.2f})" for p in positions]
    return "\n".join(lines)


def format_risk(nav: float, day_pnl_pct: float, max_daily_loss_pct_nav: float, open_positions: int, max_open_positions: int) -> str:
    room = max_daily_loss_pct_nav + day_pnl_pct
    return (
        f"NAV: ${nav:,.2f}\n"
        f"Day P&L: {day_pnl_pct:.2%} (room to daily loss cap: {room:.2%})\n"
        f"Open positions: {open_positions}/{max_open_positions}"
    )


class TelegramNotifier:
    """Sends alerts and answers bot commands. Never calls broker.place_order (rule 2)."""

    def __init__(self, broker: BrokerBase, guard: RiskGuard, settings: Settings | None = None) -> None:
        self.broker = broker
        self.guard = guard
        self.settings = settings or default_settings

    def send_alert(self, text: str) -> None:
        if not self.settings.telegram_bot_token or not self.settings.telegram_chat_id:
            logger.info("telegram not configured, alert suppressed: %s", text)
            return
        url = f"https://api.telegram.org/bot{self.settings.telegram_bot_token}/sendMessage"
        try:
            httpx.post(url, data={"chat_id": self.settings.telegram_chat_id, "text": text}, timeout=10.0)
        except httpx.HTTPError as exc:
            logger.error("failed to send telegram alert: %s", exc)

    def handle_command(self, command: str) -> str:
        """Pure dispatch shared by the bot polling loop (main.py, later phase) and tests."""
        cmd = command.strip().lower().split()[0] if command.strip() else ""
        if cmd == "/status":
            return format_status(self.broker.account_summary(), self.guard.kill_switch_active, self.settings.trading_mode)
        if cmd == "/pnl":
            return format_pnl(self.broker.account_summary())
        if cmd == "/positions":
            return format_positions(self.broker.positions())
        if cmd == "/risk":
            summary = self.broker.account_summary()
            day_pnl_pct = summary.day_pnl / summary.nav if summary.nav else 0.0
            return format_risk(
                summary.nav,
                day_pnl_pct,
                self.settings.max_daily_loss_pct_nav,
                len(self.broker.positions()),
                self.settings.max_open_positions,
            )
        if cmd == "/kill":
            self.guard.engage_kill_switch("Telegram /kill command")
            return "Kill switch ENGAGED. All open orders cancelled. New orders blocked until /resume."
        if cmd == "/resume":
            self.guard.reset_kill_switch()
            return "Kill switch reset. Trading resumed."
        if cmd in ("/scan", "/opts"):
            return "Not available yet (scanner/options builder ship in a later phase)."
        return "Unknown command. Try /status /pnl /positions /risk /kill /resume."

"""Central settings. Every safety limit in CLAUDE.md is enforced from here.

Nothing in this module may loosen a limit at runtime -- config values are the
ceiling; callers (risk/guard.py, ai/reviewer.py) may only tighten them.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

LIVE_CONFIRM_PHRASE = "I_ACCEPT_REAL_MONEY_RISK"


class TradingMode(StrEnum):
    PAPER = "paper"
    LIVE = "live"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- Trading mode safety switch ---
    trading_mode: TradingMode = TradingMode.PAPER
    live_confirm: str = ""

    # --- IB Gateway ---
    ib_host: str = "127.0.0.1"
    ib_port: int = 4002
    ib_client_id: int = 17

    tws_userid: str = ""
    tws_password: str = ""

    # --- AI layer (advisory only -- see ai/reviewer.py) ---
    anthropic_api_key: str = ""
    ai_model: str = "claude-sonnet-5"

    # --- Telegram ---
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    # --- Web terminal ---
    web_auth_token: str = "change-me"
    web_host: str = "0.0.0.0"
    web_port: int = 8000
    ws_broadcast_interval_seconds: float = 2.0

    # --- Storage ---
    database_url: str = "sqlite:///./data/omega.db"
    kill_switch_file: str = "KILL"

    # --- Hard risk limits (sane defaults per CLAUDE.md) ---
    max_daily_loss_pct_nav: float = Field(default=0.02, gt=0, le=1)
    max_position_pct_nav: float = Field(default=0.10, gt=0, le=1)
    max_open_positions: int = Field(default=8, gt=0)
    max_order_notional: float = Field(default=25_000, gt=0)
    max_options_contracts_per_order: int = Field(default=10, gt=0)
    allow_naked_short_calls: bool = False
    allow_market_orders_options: bool = False

    @field_validator("allow_naked_short_calls")
    @classmethod
    def _no_naked_calls(cls, v: bool) -> bool:
        if v:
            raise ValueError("naked short calls are never permitted (CLAUDE.md rule 4)")
        return v

    @field_validator("allow_market_orders_options")
    @classmethod
    def _no_market_options(cls, v: bool) -> bool:
        if v:
            raise ValueError("market orders on options are never permitted (CLAUDE.md rule 4)")
        return v

    @property
    def live_trading_authorized(self) -> bool:
        """Both TRADING_MODE=live AND the exact confirm phrase are required."""
        return self.trading_mode == TradingMode.LIVE and self.live_confirm == LIVE_CONFIRM_PHRASE

    @property
    def is_read_only(self) -> bool:
        """True whenever execution must be blocked and the system runs read-only."""
        if self.trading_mode == TradingMode.PAPER:
            return False
        return not self.live_trading_authorized

    @property
    def kill_switch_active(self) -> bool:
        return Path(self.kill_switch_file).exists()


def get_settings() -> Settings:
    return Settings()


settings = get_settings()

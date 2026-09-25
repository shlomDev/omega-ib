"""Market-hours-aware job scheduler: pre-market plan, open, intraday scans,
mid-session review, EOD management, post-close report.

APScheduler's cron triggers don't know about market holidays, so every job is
wrapped to check `is_trading_day` (via pandas_market_calendars' NYSE calendar)
before doing anything -- this is the "weekend/holiday handling" hardening item.
"""

from __future__ import annotations

import datetime as dt
import logging
from collections.abc import Callable

import pandas_market_calendars as mcal
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)

_NYSE = mcal.get_calendar("NYSE")


def is_trading_day(date: dt.date | None = None) -> bool:
    date = date or dt.date.today()
    schedule = _NYSE.schedule(start_date=date, end_date=date)
    return not schedule.empty


def _guarded(job: Callable[[], None]) -> Callable[[], None]:
    def wrapper() -> None:
        if not is_trading_day():
            logger.info("not a trading day, skipping scheduled job %s", getattr(job, "__name__", job))
            return
        job()

    return wrapper


def build_scheduler(
    pre_market_job: Callable[[], None] | None = None,
    open_job: Callable[[], None] | None = None,
    intraday_job: Callable[[], None] | None = None,
    mid_session_job: Callable[[], None] | None = None,
    eod_job: Callable[[], None] | None = None,
    post_close_job: Callable[[], None] | None = None,
    intraday_interval_minutes: int = 15,
    timezone: str = "America/New_York",
) -> BackgroundScheduler:
    """Wires every provided job behind an is_trading_day guard, on the schedule
    from CLAUDE.md: pre-market 08:30 ET, open 09:30, intraday every N minutes
    during the session, mid-session 12:30, EOD 15:40, post-close after the close.
    A job left as None is simply not scheduled (useful for partial wiring/tests).
    """
    scheduler = BackgroundScheduler(timezone=timezone)

    if pre_market_job:
        scheduler.add_job(_guarded(pre_market_job), CronTrigger(hour=8, minute=30, timezone=timezone), id="pre_market")
    if open_job:
        scheduler.add_job(_guarded(open_job), CronTrigger(hour=9, minute=30, timezone=timezone), id="open")
    if intraday_job:
        scheduler.add_job(
            _guarded(intraday_job),
            CronTrigger(hour="9-15", minute=f"*/{intraday_interval_minutes}", timezone=timezone),
            id="intraday",
        )
    if mid_session_job:
        scheduler.add_job(_guarded(mid_session_job), CronTrigger(hour=12, minute=30, timezone=timezone), id="mid_session")
    if eod_job:
        scheduler.add_job(_guarded(eod_job), CronTrigger(hour=15, minute=40, timezone=timezone), id="eod")
    if post_close_job:
        scheduler.add_job(_guarded(post_close_job), CronTrigger(hour=16, minute=30, timezone=timezone), id="post_close")
    return scheduler

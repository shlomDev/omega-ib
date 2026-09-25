import datetime as dt

from omega_ib.scheduler import build_scheduler, is_trading_day


def test_is_trading_day_weekday():
    # 2026-09-25 is a Friday
    assert is_trading_day(dt.date(2026, 9, 25)) is True


def test_is_trading_day_weekend():
    # 2026-09-26 is a Saturday
    assert is_trading_day(dt.date(2026, 9, 26)) is False


def test_is_trading_day_holiday():
    assert is_trading_day(dt.date(2026, 12, 25)) is False


def test_build_scheduler_only_registers_provided_jobs():
    scheduler = build_scheduler(pre_market_job=lambda: None, eod_job=lambda: None)
    job_ids = {job.id for job in scheduler.get_jobs()}
    assert job_ids == {"pre_market", "eod"}


def test_build_scheduler_registers_all_jobs():
    scheduler = build_scheduler(
        pre_market_job=lambda: None,
        open_job=lambda: None,
        intraday_job=lambda: None,
        mid_session_job=lambda: None,
        eod_job=lambda: None,
        post_close_job=lambda: None,
    )
    job_ids = {job.id for job in scheduler.get_jobs()}
    assert job_ids == {"pre_market", "open", "intraday", "mid_session", "eod", "post_close"}


def test_guarded_job_skips_on_non_trading_day(monkeypatch):
    calls = []
    monkeypatch.setattr("omega_ib.scheduler.is_trading_day", lambda: False)
    scheduler = build_scheduler(pre_market_job=lambda: calls.append(1))
    job = scheduler.get_job("pre_market")
    job.func()
    assert calls == []


def test_guarded_job_runs_on_trading_day(monkeypatch):
    calls = []
    monkeypatch.setattr("omega_ib.scheduler.is_trading_day", lambda: True)
    scheduler = build_scheduler(pre_market_job=lambda: calls.append(1))
    job = scheduler.get_job("pre_market")
    job.func()
    assert calls == [1]

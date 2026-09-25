import pandas as pd

from backtest.replay import compute_strategy_stats, format_stats_report, max_drawdown, replay
from omega_ib.config import Settings
from omega_ib.strategies.equity.momentum_breakout import MomentumBreakout


def _flat_rows(n, price=100.0, volume=1000):
    return [dict(open=price, high=price + 1, low=price - 1, close=price, volume=volume) for _ in range(n)]


def _dates(n):
    return pd.date_range("2026-01-01", periods=n, freq="D")


def test_replay_enters_and_exits_on_target(tmp_path):
    rows = _flat_rows(21)
    rows.append(dict(open=104, high=110, low=100, close=108, volume=3000))  # breakout entry
    rows.append(dict(open=108, high=109, low=107, close=108, volume=1000))  # quiet day
    rows.append(dict(open=118, high=120, low=117, close=119, volume=1000))  # target hit
    bars = pd.DataFrame(rows, index=_dates(len(rows)))
    settings = Settings(kill_switch_file=str(tmp_path / "KILL"))

    result = replay({"AAPL": bars}, [MomentumBreakout()], starting_nav=100_000.0, risk_pct=0.01, min_history=22, settings=settings)

    assert len(result.closed_trades) == 1
    trade = result.closed_trades[0]
    assert trade.symbol == "AAPL"
    assert trade.exit_reason == "target"
    assert trade.pnl > 0
    assert result.rejections == []
    assert result.equity_curve[-1][1] > 100_000.0


def test_replay_exits_on_stop_and_records_loss(tmp_path):
    rows = _flat_rows(21)
    rows.append(dict(open=104, high=110, low=100, close=108, volume=3000))  # breakout entry
    rows.append(dict(open=108, high=109, low=100, close=105, volume=1000))  # quiet day
    rows.append(dict(open=100, high=103, low=95, close=98, volume=1000))  # stop hit (~102.86)
    bars = pd.DataFrame(rows, index=_dates(len(rows)))
    settings = Settings(kill_switch_file=str(tmp_path / "KILL"))

    result = replay({"AAPL": bars}, [MomentumBreakout()], starting_nav=100_000.0, risk_pct=0.01, min_history=22, settings=settings)

    assert len(result.closed_trades) == 1
    trade = result.closed_trades[0]
    assert trade.exit_reason == "stop"
    assert trade.pnl < 0
    assert round(trade.r_multiple, 2) == -1.0


def test_replay_never_triggers_without_a_setup(tmp_path):
    bars = pd.DataFrame(_flat_rows(30), index=_dates(30))
    settings = Settings(kill_switch_file=str(tmp_path / "KILL"))
    result = replay({"AAPL": bars}, [MomentumBreakout()], min_history=22, settings=settings)
    assert result.closed_trades == []
    assert result.rejections == []


def test_replay_records_guard_rejections_when_at_position_cap(tmp_path):
    rows = _flat_rows(21)
    rows.append(dict(open=104, high=110, low=100, close=108, volume=3000))
    bars = pd.DataFrame(rows, index=_dates(len(rows)))
    settings = Settings(kill_switch_file=str(tmp_path / "KILL"), max_open_positions=1)

    result = replay(
        {"AAPL": bars, "MSFT": bars.copy()},
        [MomentumBreakout()],
        starting_nav=100_000.0,
        min_history=22,
        settings=settings,
    )
    assert any("max_open_positions" in r for r in result.rejections)


def test_max_drawdown_computation():
    curve = [(0, 100_000.0), (1, 110_000.0), (2, 90_000.0), (3, 95_000.0)]
    assert round(max_drawdown(curve), 4) == round((110_000.0 - 90_000.0) / 110_000.0, 4)


def test_max_drawdown_empty_curve():
    assert max_drawdown([]) == 0.0


def test_compute_strategy_stats_groups_by_strategy():
    from backtest.replay import ClosedTrade

    trades = [
        ClosedTrade(symbol="AAPL", strategy="momentum_breakout", direction="long", entry_date=0, exit_date=1,
                    entry_price=100.0, exit_price=110.0, quantity=10, risk_per_share=5.0, pnl=100.0, exit_reason="target"),
        ClosedTrade(symbol="MSFT", strategy="momentum_breakout", direction="long", entry_date=0, exit_date=1,
                    entry_price=100.0, exit_price=95.0, quantity=10, risk_per_share=5.0, pnl=-50.0, exit_reason="stop"),
    ]
    stats = compute_strategy_stats(trades)
    s = stats["momentum_breakout"]
    assert s.trades == 2
    assert s.wins == 1
    assert s.losses == 1
    assert s.win_rate == 0.5
    assert s.total_pnl == 50.0


def test_format_stats_report_no_trades():
    from backtest.replay import ReplayResult

    report = format_stats_report(ReplayResult())
    assert "no closed trades" in report


def test_format_stats_report_with_trades(tmp_path):
    rows = _flat_rows(21)
    rows.append(dict(open=104, high=110, low=100, close=108, volume=3000))
    rows.append(dict(open=108, high=109, low=107, close=108, volume=1000))
    rows.append(dict(open=118, high=120, low=117, close=119, volume=1000))
    bars = pd.DataFrame(rows, index=_dates(len(rows)))
    settings = Settings(kill_switch_file=str(tmp_path / "KILL"))
    result = replay({"AAPL": bars}, [MomentumBreakout()], min_history=22, settings=settings)
    report = format_stats_report(result)
    assert "momentum_breakout" in report
    assert "Max drawdown" in report
    assert "Final NAV" in report

from omega_ib.risk.portfolio import (
    PositionRisk,
    aggregate_greeks,
    beta_weighted_delta_vs_spy,
    daily_loss_gauge,
    historical_var,
    open_positions_gauge,
    sector_concentration,
    underlying_concentration,
)


def _positions():
    return [
        PositionRisk(
            symbol="AAPL", sec_type="STK", quantity=100, price=150.0, market_value=15_000.0,
            delta_shares=100, beta=1.2, sector="Technology",
        ),
        PositionRisk(
            symbol="AAPL", sec_type="OPT", quantity=-2, price=3.0, market_value=-600.0,
            delta_shares=-40, gamma=0.5, theta=-2.0, vega=1.5, beta=1.2, sector="Technology",
        ),
        PositionRisk(
            symbol="XOM", sec_type="STK", quantity=50, price=110.0, market_value=5_500.0,
            delta_shares=50, beta=0.8, sector="Energy",
        ),
    ]


def test_aggregate_greeks():
    g = aggregate_greeks(_positions())
    assert g.total_delta_shares == 110  # 100 - 40 + 50
    assert g.total_gamma == 0.5
    assert g.total_theta == -2.0
    assert g.total_vega == 1.5


def test_beta_weighted_delta_vs_spy():
    positions = _positions()
    result = beta_weighted_delta_vs_spy(positions, spy_price=500.0)
    dollar_delta = 100 * 150.0 * 1.2 + (-40) * 3.0 * 1.2 + 50 * 110.0 * 0.8
    assert result == dollar_delta / 500.0


def test_beta_weighted_delta_zero_spy_price():
    assert beta_weighted_delta_vs_spy(_positions(), spy_price=0.0) == 0.0


def test_sector_concentration_sorted_and_pct():
    exposures = sector_concentration(_positions(), nav=20_000.0)
    assert exposures[0].sector == "Technology"
    assert exposures[0].market_value == 15_000.0 - 600.0
    assert round(exposures[0].pct_of_nav, 4) == round((15_000.0 - 600.0) / 20_000.0, 4)


def test_sector_concentration_zero_nav():
    assert sector_concentration(_positions(), nav=0.0) == []


def test_underlying_concentration_groups_by_symbol():
    exposures = underlying_concentration(_positions(), nav=20_000.0)
    aapl = next(e for e in exposures if e.sector == "AAPL")
    assert aapl.market_value == 15_000.0 - 600.0


def test_historical_var_worst_tail():
    returns = [-0.05, -0.03, -0.01, 0.0, 0.01, 0.02, 0.03]
    var95 = historical_var(returns, confidence=0.95)
    assert var95 == -0.05  # worst 5% tail of 7 points -> index 0


def test_historical_var_empty():
    assert historical_var([]) == 0.0


def test_daily_loss_gauge_breach():
    gauge = daily_loss_gauge(day_pnl_pct=-0.025, max_daily_loss_pct_nav=0.02)
    assert gauge.breached is True
    assert gauge.room_remaining < 0


def test_daily_loss_gauge_ok():
    gauge = daily_loss_gauge(day_pnl_pct=-0.005, max_daily_loss_pct_nav=0.02)
    assert gauge.breached is False
    assert round(gauge.room_remaining, 3) == 0.015


def test_open_positions_gauge():
    gauge = open_positions_gauge(open_positions=8, max_open_positions=8)
    assert gauge.breached is True

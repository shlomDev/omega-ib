from omega_ib.strategies.equity.base import Signal, Strategy, rank_signals, run_strategies
from omega_ib.strategies.equity.gap_and_go import GapAndGo
from omega_ib.strategies.equity.mean_reversion import MeanReversion
from omega_ib.strategies.equity.momentum_breakout import MomentumBreakout
from omega_ib.strategies.equity.trend_pullback import TrendPullback
from omega_ib.strategies.equity.vwap_reclaim import VWAPReclaim

ALL_STRATEGIES: list[Strategy] = [
    MomentumBreakout(),
    GapAndGo(),
    MeanReversion(),
    VWAPReclaim(),
    TrendPullback(),
]

__all__ = [
    "ALL_STRATEGIES",
    "GapAndGo",
    "MeanReversion",
    "MomentumBreakout",
    "Signal",
    "Strategy",
    "TrendPullback",
    "VWAPReclaim",
    "rank_signals",
    "run_strategies",
]

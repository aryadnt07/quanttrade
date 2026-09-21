"""
Core Performance & Backtest Statistics
======================================
Stateless dataclasses for strategy and portfolio performance attribution.
"""

from dataclasses import dataclass, field
from typing import Dict
import pandas as pd


@dataclass
class BaseStats:
    """Statistik dasar performa kuantitatif."""
    initial_capital: float = 10000.0
    ending_capital: float = 0.0
    total_net_pnl_usd: float = 0.0
    roi_pct: float = 0.0

    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = 0.0

    profit_factor: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown_usd: float = 0.0
    max_drawdown_pct: float = 0.0

    avg_pnl_usd: float = 0.0
    avg_win_usd: float = 0.0
    avg_loss_usd: float = 0.0
    best_trade_usd: float = 0.0
    worst_trade_usd: float = 0.0


@dataclass
class BreakoutStats(BaseStats):
    """Statistik performa strategi Opening Range Breakout (London & NY)."""
    total_r: float = 0.0
    avg_r: float = 0.0
    core_win_rate: float = 0.0
    core_trades: int = 0
    max_drawdown_r: float = 0.0

    exit_counts: Dict[str, int] = field(default_factory=dict)
    monthly_pnl_df: pd.DataFrame = field(default_factory=pd.DataFrame)

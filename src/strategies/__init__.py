"""
Quantitative Trading Strategies Package
=======================================
Canonical implementations of multi-session trading strategies:
1. asian_mr   : Asian Mean Reversion (Statistical Arbitrage)
2. london_orb : London Pit Opening Range Breakout
3. ny_orb     : New York Opening Range Breakout
4. portfolio  : Multi-Regime Master Portfolio Engine
"""

from .asian_mr.backtester import Backtester as AsianBacktester
from .london_orb.backtester import LondonBacktester
from .ny_orb.backtester import NYBacktester
from .portfolio.engine import PortfolioEngine

__all__ = [
    "AsianBacktester",
    "LondonBacktester",
    "NYBacktester",
    "PortfolioEngine",
]

"""
Core Domain Primitives
======================
Stateless types, pure mathematical indicators, and common domain statistics.
Zero external framework dependencies (pure Python, NumPy, Pandas only).
"""

from .types import (
    Direction,
    ExitReason,
    Signal,
    TradeResult,
    PortfolioTradeRecord,
    OrderIntent,
    ExitIntent,
    AccountStatus,
    OrderResult,
)
from .interfaces import IBroker, IStrategy, ILiveStrategy

__all__ = [
    "Direction",
    "ExitReason",
    "Signal",
    "TradeResult",
    "PortfolioTradeRecord",
    "OrderIntent",
    "ExitIntent",
    "AccountStatus",
    "OrderResult",
    "IBroker",
    "IStrategy",
    "ILiveStrategy",
]


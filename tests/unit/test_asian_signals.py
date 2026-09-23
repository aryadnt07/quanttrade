"""
Unit Tests for src.strategies.asian_mr.signals
==============================================
"""

import unittest
from datetime import datetime, timezone
import pandas as pd
import numpy as np

from src.strategies.asian_mr.signals import (
    compute_asian_indicators,
    check_entry_signal,
    check_exit_conditions,
    is_in_entry_window,
    passes_volatility_filter,
)
from src.core.types import Direction, ExitReason, Signal


class TestAsianSignals(unittest.TestCase):

    def test_is_in_entry_window(self):
        # 01:00 UTC is within window (01:00 - 04:30 UTC)
        dt_in = pd.Timestamp("2026-09-21 02:15:00", tz="UTC")
        self.assertTrue(is_in_entry_window(dt_in))

        # 05:00 UTC is outside window
        dt_out = pd.Timestamp("2026-09-21 05:00:00", tz="UTC")
        self.assertFalse(is_in_entry_window(dt_out))

    def test_passes_volatility_filter(self):
        # Normal ATR passes
        self.assertTrue(passes_volatility_filter(1.5, 1.2))
        # NaN fails
        self.assertFalse(passes_volatility_filter(np.nan, 1.2))
        # Below min threshold (0.7) fails
        self.assertFalse(passes_volatility_filter(0.4, 1.2))

    def test_check_exit_conditions(self):
        sig = Signal(
            bar_index=0,
            datetime=pd.Timestamp("2026-09-21 02:00:00", tz="UTC"),
            direction=Direction.LONG,
            entry_price=2000.0,
            stop_loss=1990.0,
            take_profit=2010.0,
        )

        # TP when Z in [-0.5, 0.5]
        row_tp = pd.Series({
            "datetime": pd.Timestamp("2026-09-21 02:15:00", tz="UTC"),
            "high": 2005.0,
            "low": 1998.0,
            "close": 2003.0,
            "zscore": 0.0,
        })
        self.assertEqual(check_exit_conditions(row_tp, sig), ExitReason.TAKE_PROFIT_Z)

        # SL when low <= stop_loss
        row_sl = pd.Series({
            "datetime": pd.Timestamp("2026-09-21 02:15:00", tz="UTC"),
            "high": 1995.0,
            "low": 1988.0,
            "close": 1989.0,
            "zscore": -2.0,
        })
        self.assertEqual(check_exit_conditions(row_sl, sig), ExitReason.STOP_LOSS)

    def test_check_exit_conditions_pessimistic_sl_precedence(self):
        """Forensic test: when same candle breaches both TP and SL, SL must take precedence."""
        sig = Signal(
            bar_index=0,
            datetime=pd.Timestamp("2026-09-21 02:00:00", tz="UTC"),
            direction=Direction.LONG,
            entry_price=2000.0,
            stop_loss=1990.0,
            take_profit=2010.0,
        )

        # High breaches TP (2015 >= 2010) AND Low breaches SL (1985 <= 1990)
        row_both = pd.Series({
            "datetime": pd.Timestamp("2026-09-21 02:05:00", tz="UTC"),
            "high": 2015.0,
            "low": 1985.0,
            "close": 2005.0,
            "zscore": 0.0,
        })
        # Must return STOP_LOSS, eliminating optimistic bias
        self.assertEqual(check_exit_conditions(row_both, sig), ExitReason.STOP_LOSS)


if __name__ == "__main__":
    unittest.main()

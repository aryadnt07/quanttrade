"""
Unit Tests for src.strategies.london_orb.signals
================================================
"""

import unittest
import pandas as pd
import numpy as np

from src.strategies.london_orb.signals import compute_london_indicators, form_london_or_box
from src.core.types import Direction


class TestLondonSignals(unittest.TestCase):

    def setUp(self):
        dates = pd.date_range("2026-09-21 07:00:00", periods=50, freq="5min", tz="UTC")
        self.df = pd.DataFrame({
            "datetime": dates,
            "open": 2000.0,
            "high": 2005.0,
            "low": 1995.0,
            "close": 2002.0,
            "volume": 100,
        })

    def test_compute_london_indicators(self):
        df_ind = compute_london_indicators(self.df)
        self.assertIn("tr", df_ind.columns)
        self.assertIn("atr14", df_ind.columns)
        self.assertIn("tr_sma20", df_ind.columns)

    def test_form_london_or_box(self):
        df_ind = compute_london_indicators(self.df)
        box = form_london_or_box(df_ind)
        # Since bars exist between 08:00 and 08:15 UTC (bars at 08:00, 08:05, 08:10)
        self.assertIsNotNone(box)
        high, low, rng = box
        self.assertGreater(high, low)
        self.assertAlmostEqual(rng, high - low, places=5)

    def test_trade_manager_m1_duration(self):
        """Forensic test: M1 bars must increment duration by actual elapsed minutes, not hardcoded 5.0 min."""
        from src.strategies.london_orb.trade_manager import LondonTradeManager
        from src.strategies.london_orb.signals import LondonSignal

        tm = LondonTradeManager(current_capital=10000.0)
        t0 = pd.Timestamp("2026-09-21 08:15:00", tz="UTC")
        sig = LondonSignal(
            datetime=t0,
            direction=Direction.BUY,
            entry_price=2000.0,
            stop_loss=1990.0,
            take_profit=2020.0,
            initial_risk=10.0,
            lor_high=2000.0,
            lor_low=1990.0,
            lor_range=10.0,
        )
        tm.open_position(sig)

        # Bar 1: 1 minute later
        t1 = pd.Timestamp("2026-09-21 08:16:00", tz="UTC")
        row1 = pd.Series({"datetime": t1, "high": 2005.0, "low": 1998.0, "close": 2002.0})
        tm.update_bar(row1)
        self.assertEqual(tm.duration_minutes, 1.0)

        # Bar 2: 3 minutes later
        t2 = pd.Timestamp("2026-09-21 08:18:00", tz="UTC")
        row2 = pd.Series({"datetime": t2, "high": 2006.0, "low": 1999.0, "close": 2003.0})
        tm.update_bar(row2)
        self.assertEqual(tm.duration_minutes, 3.0)


if __name__ == "__main__":
    unittest.main()

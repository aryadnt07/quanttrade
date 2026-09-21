"""
Unit Tests for src.strategies.ny_orb.signals
============================================
"""

import unittest
import pandas as pd
import numpy as np

from src.strategies.ny_orb.signals import compute_ny_indicators, form_ny_or_box
from src.core.types import Direction


class TestNYSignals(unittest.TestCase):

    def setUp(self):
        dates = pd.date_range("2026-09-21 12:00:00", periods=50, freq="5min", tz="UTC")
        self.df = pd.DataFrame({
            "datetime": dates,
            "open": 2000.0,
            "high": 2005.0,
            "low": 1995.0,
            "close": 2002.0,
            "volume": 100,
        })

    def test_compute_ny_indicators(self):
        df_ind = compute_ny_indicators(self.df)
        self.assertIn("tr", df_ind.columns)
        self.assertIn("atr14", df_ind.columns)
        self.assertIn("tr_sma20", df_ind.columns)

    def test_form_ny_or_box(self):
        df_ind = compute_ny_indicators(self.df)
        box = form_ny_or_box(df_ind)
        # Since bars exist between 13:30 and 13:45 UTC
        self.assertIsNotNone(box)
        high, low, rng = box
        self.assertGreater(high, low)
        self.assertAlmostEqual(rng, high - low, places=5)


if __name__ == "__main__":
    unittest.main()

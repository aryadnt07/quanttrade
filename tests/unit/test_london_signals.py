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


if __name__ == "__main__":
    unittest.main()

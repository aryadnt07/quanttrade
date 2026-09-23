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

    def test_dynamic_dst_winter_vs_summer(self):
        """Forensic test: Wall Street open in winter (EST) is 14:30 UTC, summer (EDT) is 13:30 UTC."""
        # Winter date: 2026-01-15 (EST, UTC-5)
        # 09:30 AM EST = 14:30 UTC
        dates_winter = pd.date_range("2026-01-15 13:00:00", periods=30, freq="5min", tz="UTC")
        df_winter = pd.DataFrame({
            "datetime": dates_winter,
            "open": 2000.0,
            "high": 2005.0,
            "low": 1995.0,
            "close": 2002.0,
            "volume": 100,
        })
        # Set specific high on 14:30 bar
        df_winter.loc[df_winter["datetime"] == pd.Timestamp("2026-01-15 14:30:00", tz="UTC"), "high"] = 2050.0

        df_ind_winter = compute_ny_indicators(df_winter)
        # In winter, 14:30 UTC is 09:30 AM America/New_York
        self.assertTrue(pd.notna(df_ind_winter["or_high"].iloc[0]))
        self.assertEqual(df_ind_winter["or_high"].iloc[0], 2050.0)


if __name__ == "__main__":
    unittest.main()

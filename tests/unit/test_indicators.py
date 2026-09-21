"""
Unit Tests for src.core.indicators
==================================
Tests:
- calc_sma
- calc_ema
- calc_true_range
- calc_atr
- calc_rsi
- calc_zscore
"""

import unittest
import numpy as np
import pandas as pd

from src.core.indicators import (
    calc_sma,
    calc_ema,
    calc_rolling_std,
    calc_zscore,
    calc_rsi,
    calc_true_range,
    calc_atr,
    calc_atr_sma,
    calc_adx,
)


class TestCoreIndicators(unittest.TestCase):

    def setUp(self):
        np.random.seed(42)
        n = 100
        close = 2000.0 + np.cumsum(np.random.randn(n) * 2)
        high = close + np.abs(np.random.randn(n) * 1.5)
        low = close - np.abs(np.random.randn(n) * 1.5)
        open_ = (high + low) / 2.0
        volume = np.random.randint(100, 1000, n)
        dates = pd.date_range("2026-01-01", periods=n, freq="5min", tz="UTC")

        self.df = pd.DataFrame({
            "datetime": dates,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        })

    def test_calc_sma(self):
        sma = calc_sma(self.df["close"], 10)
        self.assertEqual(len(sma), len(self.df))
        self.assertTrue(pd.isna(sma.iloc[0]))
        self.assertFalse(pd.isna(sma.iloc[9]))
        expected_10 = self.df["close"].iloc[:10].mean()
        self.assertAlmostEqual(sma.iloc[9], expected_10, places=5)

    def test_calc_ema(self):
        ema = calc_ema(self.df["close"], 10)
        self.assertEqual(len(ema), len(self.df))
        self.assertFalse(pd.isna(ema.iloc[-1]))

    def test_calc_true_range_and_atr(self):
        tr = calc_true_range(self.df)
        self.assertEqual(len(tr), len(self.df))
        self.assertTrue((tr >= 0).all())

        atr = calc_atr(self.df, 14)
        self.assertEqual(len(atr), len(self.df))
        self.assertTrue((atr.dropna() > 0).all())

    def test_calc_rsi(self):
        rsi = calc_rsi(self.df["close"], 14)
        self.assertEqual(len(rsi), len(self.df))
        valid_rsi = rsi.dropna()
        self.assertTrue((valid_rsi >= 0).all() and (valid_rsi <= 100).all())

    def test_calc_zscore(self):
        mean = calc_sma(self.df["close"], 20)
        std = calc_rolling_std(self.df["close"], 20, min_sigma=0.01)
        z = calc_zscore(self.df["close"], mean, std)
        valid_z = z.dropna()
        self.assertTrue(len(valid_z) > 0)
        self.assertTrue(np.abs(valid_z.mean()) < 1.0)


if __name__ == "__main__":
    unittest.main()

"""
Integration Tests for Asian Mean Reversion Backtest
===================================================
"""

import unittest
import pandas as pd
import numpy as np

from src.strategies.asian_mr.backtester import Backtester
from src.strategies.asian_mr.signals import compute_asian_indicators
from src.data.loader import load_csv, get_default_data_path


class TestIntegrationAsianBacktest(unittest.TestCase):

    def test_asian_backtest_runs(self):
        path = get_default_data_path()
        df = load_csv(path)
        # Run on a 2000-bar sample for fast execution
        sample_df = df.iloc[:2000].copy()
        sample_df = compute_asian_indicators(sample_df)

        bt = Backtester(sample_df)
        stats = bt.run()
        self.assertIsNotNone(stats)
        self.assertGreaterEqual(stats.total_trades, 0)
        self.assertEqual(len(bt.trades), stats.total_trades)


if __name__ == "__main__":
    unittest.main()

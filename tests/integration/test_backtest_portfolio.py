"""
Integration Tests for Master Portfolio Backtest Engine
======================================================
"""

import unittest
import pandas as pd
import numpy as np

from src.strategies.portfolio.engine import PortfolioEngine
from src.data.loader import load_csv, get_default_data_path


class TestIntegrationPortfolioBacktest(unittest.TestCase):

    def test_portfolio_engine_sample_run(self):
        path = get_default_data_path()
        df = load_csv(path)
        sample_df = df.iloc[:3000].copy()

        engine = PortfolioEngine(sample_df)
        stats = engine.run()
        self.assertIsNotNone(stats)
        self.assertGreater(stats.ending_capital, 0)
        self.assertIsNotNone(stats.monthly_pnl_df)


if __name__ == "__main__":
    unittest.main()

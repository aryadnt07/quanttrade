"""
Unit Tests for TickPortfolioEngine and TickLoader
=================================================
"""

import unittest
from datetime import datetime, timezone, date
import numpy as np
import pandas as pd

from src.data.tick_loader import TickDataset
from src.strategies.portfolio.tick_engine import TickPortfolioEngine, ActiveTickPosition
from src.core.types import ExitReason


class TestTickEngine(unittest.TestCase):

    def setUp(self):
        # Create small synthetic tick dataset (1 day)
        base_dt = pd.Timestamp("2026-08-10 07:55:00", tz="UTC")
        n = 500
        dts = pd.date_range(base_dt, periods=n, freq="1s")
        ts_ms = dts.astype(np.int64) // 10**6

        # Simulasikan harga:
        # 08:00 - 08:15 (t=300 to t=1200): OR box 2000.0 to 2010.0
        # 08:20 (t=1500): Breakout di 2012.0
        bids = np.full(n, 2005.0)
        # Bids between 08:00 (idx=300) and 08:14:59:
        bids[300:400] = 2002.0
        bids[400:500] = 2008.0
        asks = bids + 0.30  # Spread 0.30

        self.tick_ds = TickDataset(
            timestamps_ms=ts_ms,
            datetimes=dts,
            asks=asks,
            bids=bids,
            spreads=asks - bids,
            day_slices={date(2026, 8, 10): (0, n)},
            unique_dates=[date(2026, 8, 10)],
        )

        # Synthetic M5 dataframe
        m5_dts = pd.date_range("2026-08-10 00:00:00", periods=100, freq="5min", tz="UTC")
        self.df_m5 = pd.DataFrame({
            "datetime": m5_dts,
            "open": 2005.0,
            "high": 2010.0,
            "low": 2000.0,
            "close": 2005.0,
            "volume": 100,
        })

    def test_tick_dataset_properties(self):
        self.assertEqual(self.tick_ds.total_ticks, 500)
        self.assertIn(date(2026, 8, 10), self.tick_ds.day_slices)
        s, e = self.tick_ds.day_slices[date(2026, 8, 10)]
        self.assertEqual(s, 0)
        self.assertEqual(e, 500)

    def test_tick_portfolio_engine_initialization(self):
        engine = TickPortfolioEngine(self.tick_ds, self.df_m5, initial_capital=10000.0)
        self.assertEqual(engine.initial_capital, 10000.0)
        self.assertEqual(engine.current_capital, 10000.0)
        self.assertIsNotNone(engine.df_m5_london)
        self.assertIsNotNone(engine.df_m5_ny)
        self.assertIsNotNone(engine.df_m5_asian)

    def test_active_position_pnl_and_excursion(self):
        pos = ActiveTickPosition(
            strategy="LONDON_ORB",
            direction="BUY",
            entry_datetime=pd.Timestamp("2026-08-10 08:20:00", tz="UTC"),
            entry_price=2010.30,  # Bought at Ask
            stop_loss=2000.0,
            take_profit=2030.0,
            lot_size=1.0,
            initial_risk=10.30,
            target_rr=2.0,
            entry_ms=1000,
        )
        # Sell at Bid 2015.00 -> Profit +4.70 pts -> $470 USD
        bid = 2015.00
        pnl_pts = bid - pos.entry_price
        pnl_usd = pnl_pts * pos.lot_size * 100.0
        self.assertAlmostEqual(pnl_pts, 4.70, places=2)
        self.assertAlmostEqual(pnl_usd, 470.0, places=1)


if __name__ == "__main__":
    unittest.main()

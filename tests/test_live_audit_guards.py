"""
Automated Verification Suite for Live Trading Security & Audit Fixes (P0 & P1)
==============================================================================
Tests:
1. PID Single-Instance Lockfile (P0-002)
2. Broker Server UTC Offset Detection (P0-003)
3. Safe Order Send with IPC Timeout (P0-004)
4. In-Flight Order Mutex Lock (P0-001)
5. Daily Loss Circuit Breaker (P1-003)
6. Asia MR Exit Logic Parity (P1-001) & Close Position Verification (P1-005)
"""

import os
import sys
import time
import unittest
from datetime import datetime, timezone, date
from unittest.mock import MagicMock, patch

sys.path.insert(0, ".")

import pandas as pd
import numpy as np
from live.live_runner import LivePortfolioTrader, is_process_running
from live.mt5_connector import MT5Connector, OrderResult
from configs import live_config as lcfg


class TestLiveAuditGuards(unittest.TestCase):

    def setUp(self):
        self.test_lock_file = "test_bot.lock"
        if os.path.exists(self.test_lock_file):
            try:
                os.remove(self.test_lock_file)
            except OSError:
                pass

    def tearDown(self):
        if os.path.exists(self.test_lock_file):
            try:
                os.remove(self.test_lock_file)
            except OSError:
                pass

    # ─────────────────────────────────────────────────────────────
    # TEST 1: PID SINGLE-INSTANCE LOCKFILE (P0-002)
    # ─────────────────────────────────────────────────────────────
    def test_pid_lock_lifecycle(self):
        trader = LivePortfolioTrader()
        with patch.object(lcfg, "PID_LOCK_FILE", self.test_lock_file):
            # 1. Acquire lock
            self.assertTrue(trader._acquire_pid_lock())
            self.assertTrue(os.path.exists(self.test_lock_file))
            with open(self.test_lock_file, "r") as f:
                content = int(f.read().strip())
            self.assertEqual(content, os.getpid())

            # 2. Second instance with running PID blocks
            with patch("live.live_runner.is_process_running", return_value=True):
                with open(self.test_lock_file, "w") as f:
                    f.write("999998")  # Different PID that is "running"
                trader2 = LivePortfolioTrader()
                self.assertFalse(trader2._acquire_pid_lock())

            # 3. Stale lock (dead PID) is overwritten
            with patch("live.live_runner.is_process_running", return_value=False):
                with open(self.test_lock_file, "w") as f:
                    f.write("999999")  # Dead PID
                trader3 = LivePortfolioTrader()
                self.assertTrue(trader3._acquire_pid_lock())
                with open(self.test_lock_file, "r") as f:
                    content = int(f.read().strip())
                self.assertEqual(content, os.getpid())

            # 4. Release lock
            trader._lock_acquired = True
            trader._release_pid_lock()
            self.assertFalse(os.path.exists(self.test_lock_file))

    # ─────────────────────────────────────────────────────────────
    # TEST 2: BROKER SERVER UTC OFFSET AUTO-DETECTION (P0-003)
    # ─────────────────────────────────────────────────────────────
    def test_broker_server_utc_offset(self):
        connector = MT5Connector()
        # Default config auto-detect 999
        with patch.object(lcfg, "BROKER_SERVER_OFFSET_HOURS", 999):
            connector._cached_broker_offset_sec = None
            offset = connector.get_broker_server_utc_offset_seconds()
            self.assertIsInstance(offset, int)
            # Second call returns cached value
            self.assertEqual(connector.get_broker_server_utc_offset_seconds(), offset)

        # Configured manual override
        with patch.object(lcfg, "BROKER_SERVER_OFFSET_HOURS", 2):
            connector._cached_broker_offset_sec = None
            self.assertEqual(connector.get_broker_server_utc_offset_seconds(), 7200)

    # ─────────────────────────────────────────────────────────────
    # TEST 3: SAFE ORDER SEND WITH IPC TIMEOUT (P0-004)
    # ─────────────────────────────────────────────────────────────
    def test_safe_order_send_timeout(self):
        connector = MT5Connector()
        # Test hanging MT5 IPC
        def slow_order_send(req):
            time.sleep(1.0)
            return MagicMock(retcode=10009)

        with patch("live.mt5_connector.mt5.order_send", side_effect=slow_order_send):
            res = connector._safe_order_send({"action": 1}, timeout_sec=0.1)
            self.assertIsNone(res, "Harus mengembalikan None jika order_send timeout.")

    # ─────────────────────────────────────────────────────────────
    # TEST 4: IN-FLIGHT ORDER MUTEX LOCK (P0-001)
    # ─────────────────────────────────────────────────────────────
    def test_order_in_flight_mutex_guards(self):
        trader = LivePortfolioTrader()
        trader.today_schedule = {
            "ASIAN_START": (0, 0), "ASIAN_END": (23, 59),
            "LONDON_ENTRY_START": (0, 0), "LONDON_ENTRY_END": (23, 59),
            "NY_ENTRY_START": (0, 0), "NY_ENTRY_END": (23, 59)
        }
        df_dummy = pd.DataFrame({
            "datetime": pd.date_range("2026-09-18", periods=100, freq="5min", tz="UTC"),
            "open": [4000.0]*100, "high": [4010.0]*100, "low": [3990.0]*100, "close": [4005.0]*100, "volume": [100]*100
        })

        # Set mutex to True for Asian
        trader._order_in_flight["ASIAN"] = True
        with patch.object(trader.connector, "open_market_order") as mock_open:
            trader._evaluate_asian_mr(df_dummy, datetime.now(timezone.utc), {"spread": 0.1, "bid": 4000, "ask": 4001}, 1000.0)
            mock_open.assert_not_called()

        # Set mutex to True for London
        trader._order_in_flight["LONDON"] = True
        with patch.object(trader.connector, "open_market_order") as mock_open:
            trader._evaluate_london_orb(df_dummy, datetime.now(timezone.utc), {"spread": 0.1, "bid": 4000, "ask": 4001}, 1000.0, [])
            mock_open.assert_not_called()

        # Set mutex to True for NY
        trader._order_in_flight["NY"] = True
        with patch.object(trader.connector, "open_market_order") as mock_open:
            trader._evaluate_ny_orb(df_dummy, datetime.now(timezone.utc), {"spread": 0.1, "bid": 4000, "ask": 4001}, 1000.0, [])
            mock_open.assert_not_called()

    # ─────────────────────────────────────────────────────────────
    # TEST 5: DAILY LOSS CIRCUIT BREAKER (P1-003)
    # ─────────────────────────────────────────────────────────────
    def test_daily_circuit_breaker(self):
        trader = LivePortfolioTrader()
        today = datetime.now(timezone.utc).date()
        trader.current_trading_day = today
        trader.starting_daily_equity = 1000.0
        trader.daily_circuit_breaker_tripped = False

        # Simulate account equity dropping to $940 (6% loss > 5% threshold)
        mock_acc = MagicMock()
        mock_acc.equity = 940.0
        mock_acc.balance = 940.0

        df_dummy = pd.DataFrame({
            "datetime": pd.date_range("2026-09-18", periods=100, freq="5min", tz="UTC"),
            "open": [4000.0]*100, "high": [4010.0]*100, "low": [3990.0]*100, "close": [4005.0]*100, "volume": [100]*100
        })

        with patch.object(trader.connector, "get_account_status", return_value=mock_acc), \
             patch.object(trader.connector, "get_tick", return_value={"bid": 4000, "ask": 4001, "spread": 0.1}), \
             patch.object(trader.connector, "get_live_rates", return_value=df_dummy):
            
            # Run tick cycle check
            with patch.object(trader, "_is_in_any_active_window", return_value=True), \
                 patch.object(trader, "_manage_open_positions"):
                trader._tick_cycle(datetime.now(timezone.utc))

            self.assertTrue(trader.daily_circuit_breaker_tripped)
            self.assertTrue(trader.trades_today["ASIAN"])
            self.assertTrue(trader.trades_today["LONDON"])
            self.assertTrue(trader.trades_today["NY"])

    # ─────────────────────────────────────────────────────────────
    # TEST 6: ASIA MR EXIT CONDITIONS & CLOSE CHECK (P1-001 & P1-005)
    # ─────────────────────────────────────────────────────────────
    def test_asia_mr_exit_conditions(self):
        trader = LivePortfolioTrader()
        trader.today_schedule = {"ASIAN_CUTOFF": (6, 0)}

        now_utc = datetime(2026, 9, 18, 3, 0, 0, tzinfo=timezone.utc)
        # Position opened 65 minutes ago (Time stop should trigger)
        open_time = now_utc.timestamp() - 65 * 60

        mock_pos = MagicMock()
        mock_pos.ticket = 12345
        mock_pos.profit = 15.0
        mock_pos.comment = "AsiaMR-FLG"
        mock_pos.type = 0  # BUY
        mock_pos.time = open_time

        # Mock df_asia indicators
        mock_df = pd.DataFrame({"zscore": [-0.3, -0.3, -0.3]})

        with patch("live.live_runner.compute_asian_indicators", return_value=mock_df), \
             patch.object(trader.connector, "get_broker_server_utc_offset_seconds", return_value=0), \
             patch.object(trader.connector, "close_position", return_value=OrderResult(True, 10009, 12345, 4000.0, 0.1, "Closed")) as mock_close:

            # 1. Time stop triggers at 65 min
            trader._manage_open_positions([mock_pos], mock_df, now_utc)
            mock_close.assert_called_with(12345, comment="TimeStop-60m")

        # 2. Hard cut triggers when |Z| >= 3.2
        mock_pos.time = now_utc.timestamp() - 10 * 60  # Only 10 min old
        mock_df_extreme = pd.DataFrame({"zscore": [-3.5, -3.5, -3.5]})
        with patch("live.live_runner.compute_asian_indicators", return_value=mock_df_extreme), \
             patch.object(trader.connector, "get_broker_server_utc_offset_seconds", return_value=0), \
             patch.object(trader.connector, "close_position", return_value=OrderResult(True, 10009, 12345, 4000.0, 0.1, "Closed")) as mock_close:

            trader._manage_open_positions([mock_pos], mock_df_extreme, now_utc)
            mock_close.assert_called_with(12345, comment="HardCut-Z3.2")

        # 3. Z-Exit triggers when Z in [-0.5, 0.5] (e.g. Z = -0.4 for BUY)
        mock_pos.time = now_utc.timestamp() - 10 * 60
        mock_df_tp = pd.DataFrame({"zscore": [-0.4, -0.4, -0.4]})
        with patch("live.live_runner.compute_asian_indicators", return_value=mock_df_tp), \
             patch.object(trader.connector, "get_broker_server_utc_offset_seconds", return_value=0), \
             patch.object(trader.connector, "close_position", return_value=OrderResult(True, 10009, 12345, 4000.0, 0.1, "Closed")) as mock_close:

            trader._manage_open_positions([mock_pos], mock_df_tp, now_utc)
            mock_close.assert_called_with(12345, comment="TP-Z-Neutral")


if __name__ == "__main__":
    unittest.main()

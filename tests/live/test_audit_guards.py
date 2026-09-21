"""
Automated Verification Suite for Live Trading Security & Audit Fixes (P0 & P1)
==============================================================================
Institutional Pre-Check & Guards Test Suite:
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
import json
import unittest
from datetime import datetime, timezone, date
from unittest.mock import MagicMock, patch

import pandas as pd
import numpy as np

from src.execution.runner import LivePortfolioTrader, is_process_running
from src.execution.mt5_connector import MT5Connector, OrderResult
from src.execution import config as lcfg
from src.core.types import Direction, Signal


class TestLiveAuditGuards(unittest.TestCase):

    def setUp(self):
        self.test_lock_file = "test_bot_live.lock"
        if os.path.exists(self.test_lock_file):
            try:
                os.remove(self.test_lock_file)
            except OSError:
                pass
        self.patcher_tg = patch("src.execution.notifications.telegram.TelegramNotifier.send_message", return_value=True)
        self.patcher_tg.start()

    def tearDown(self):
        self.patcher_tg.stop()
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
            with patch("src.execution.runner.is_process_running", return_value=True):
                with open(self.test_lock_file, "w") as f:
                    f.write("999998")
                trader2 = LivePortfolioTrader()
                self.assertFalse(trader2._acquire_pid_lock())

            # 3. Stale lock (dead PID) is overwritten
            with patch("src.execution.runner.is_process_running", return_value=False):
                with open(self.test_lock_file, "w") as f:
                    f.write("999999")
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
        with patch.object(lcfg, "BROKER_SERVER_OFFSET_HOURS", 999):
            connector._cached_broker_offset_sec = None
            offset = connector.get_broker_server_utc_offset_seconds()
            self.assertIsInstance(offset, int)
            self.assertEqual(connector.get_broker_server_utc_offset_seconds(), offset)

        with patch.object(lcfg, "BROKER_SERVER_OFFSET_HOURS", 2):
            connector._cached_broker_offset_sec = None
            self.assertEqual(connector.get_broker_server_utc_offset_seconds(), 7200)

    # ─────────────────────────────────────────────────────────────
    # TEST 3: SAFE ORDER SEND WITH IPC TIMEOUT (P0-004)
    # ─────────────────────────────────────────────────────────────
    def test_safe_order_send_timeout(self):
        connector = MT5Connector()
        def slow_order_send(req):
            time.sleep(1.0)
            return MagicMock(retcode=10009)

        with patch("src.execution.mt5_connector.mt5.order_send", side_effect=slow_order_send):
            res = connector._safe_order_send({"action": 1}, timeout_sec=0.1)
            self.assertIsNone(res, "Harus mengembalikan None jika order_send timeout.")

    # ─────────────────────────────────────────────────────────────
    # TEST 4: IN-FLIGHT ORDER MUTEX LOCK (P0-001)
    # ─────────────────────────────────────────────────────────────
    def test_in_flight_mutex_blocks_concurrency(self):
        trader = LivePortfolioTrader()
        trader.today_schedule = {
            "ASIAN_START": (1, 0), "ASIAN_END": (4, 30),
            "LONDON_ENTRY_START": (8, 15), "LONDON_ENTRY_END": (11, 30),
            "NY_ENTRY_START": (13, 45), "NY_ENTRY_END": (16, 30),
        }
        trader.london_or_high = 4000.0
        trader.london_or_low = 3990.0
        trader.london_or_range = 10.0
        trader.ny_or_high = 4000.0
        trader.ny_or_low = 3990.0
        trader.ny_or_range = 10.0

        trader._order_in_flight["ASIAN"] = True
        with patch.object(trader.connector, "open_market_order") as mock_open:
            trader._evaluate_asian_mr(pd.DataFrame(), datetime(2026, 9, 21, 2, 0, tzinfo=timezone.utc), {"spread": 0.1}, 1000.0)
            mock_open.assert_not_called()

        trader._order_in_flight["LONDON"] = True
        with patch.object(trader.connector, "open_market_order") as mock_open:
            trader._evaluate_london_orb(pd.DataFrame(), datetime(2026, 9, 21, 9, 0, tzinfo=timezone.utc), {"ask": 4005.0, "bid": 4004.0, "spread": 0.1}, 1000.0, [])
            mock_open.assert_not_called()

        trader._order_in_flight["NY"] = True
        with patch.object(trader.connector, "open_market_order") as mock_open:
            trader._evaluate_ny_orb(pd.DataFrame(), datetime(2026, 9, 21, 14, 0, tzinfo=timezone.utc), {"ask": 4005.0, "bid": 4004.0, "spread": 0.1}, 1000.0, [])
            mock_open.assert_not_called()

    # ─────────────────────────────────────────────────────────────
    # TEST 5: DAILY LOSS CIRCUIT BREAKER (P1-003)
    # ─────────────────────────────────────────────────────────────
    def test_daily_circuit_breaker_tripping(self):
        test_cb_file = "test_daily_cb.json"
        trader = LivePortfolioTrader()
        test_date = date(2026, 9, 21)
        trader.starting_daily_equity = 1000.0
        trader.daily_circuit_breaker_tripped = False

        with patch.object(trader.risk_manager, "get_daily_state_path", return_value=test_cb_file):
            trader._check_daily_circuit_breaker(current_equity=960.0, today_date=test_date)
            self.assertFalse(trader.daily_circuit_breaker_tripped)

            trader._check_daily_circuit_breaker(current_equity=940.0, today_date=test_date)
            self.assertTrue(trader.daily_circuit_breaker_tripped)

        if os.path.exists(test_cb_file):
            try:
                os.remove(test_cb_file)
            except OSError:
                pass


    # ─────────────────────────────────────────────────────────────
    # TEST 6: ASIA MR SPECIAL EXITS (P1-001)
    # ─────────────────────────────────────────────────────────────
    def test_asia_mr_special_exits(self):
        trader = LivePortfolioTrader()
        trader.today_schedule = {"ASIAN_CUTOFF": (6, 0)}

        now_utc = datetime(2026, 9, 21, 3, 0, tzinfo=timezone.utc)
        mock_pos = MagicMock(
            ticket=12345, profit=15.0, comment="AsiaMR-FLG",
            type=0, time=now_utc.timestamp() - 65 * 60, price_open=4000.0, sl=3990.0, tp=4010.0, volume=0.1
        )
        mock_df = pd.DataFrame({"zscore": [-0.3, -0.3, -0.3]})

        # Time-stop 60m
        with patch("src.execution.runner.compute_asian_indicators", return_value=mock_df), \
             patch.object(trader.connector, "get_broker_server_utc_offset_seconds", return_value=0), \
             patch.object(trader.connector, "close_position", return_value=OrderResult(True, 10009, 12345, 4000.0, 0.1, "Closed")) as mock_close:
            trader._manage_open_positions([mock_pos], mock_df, now_utc)
            mock_close.assert_called_with(12345, comment="TimeStop-60m")

        # Hard Cut Z >= 3.2
        mock_pos.time = now_utc.timestamp() - 10 * 60
        mock_df_extreme = pd.DataFrame({"zscore": [-3.5, -3.5, -3.5]})
        with patch("src.execution.runner.compute_asian_indicators", return_value=mock_df_extreme), \
             patch.object(trader.connector, "get_broker_server_utc_offset_seconds", return_value=0), \
             patch.object(trader.connector, "close_position", return_value=OrderResult(True, 10009, 12345, 4000.0, 0.1, "Closed")) as mock_close:
            trader._manage_open_positions([mock_pos], mock_df_extreme, now_utc)
            mock_close.assert_called_with(12345, comment="HardCut-Z3.2")

        # TP Z-Neutral [-0.5, 0.5]
        mock_pos.time = now_utc.timestamp() - 10 * 60
        mock_df_tp = pd.DataFrame({"zscore": [-0.4, -0.4, -0.4]})
        with patch("src.execution.runner.compute_asian_indicators", return_value=mock_df_tp), \
             patch.object(trader.connector, "get_broker_server_utc_offset_seconds", return_value=0), \
             patch.object(trader.connector, "close_position", return_value=OrderResult(True, 10009, 12345, 4000.0, 0.1, "Closed")) as mock_close:
            trader._manage_open_positions([mock_pos], mock_df_tp, now_utc)
            mock_close.assert_called_with(12345, comment="TP-Z-Neutral")


if __name__ == "__main__":
    unittest.main()

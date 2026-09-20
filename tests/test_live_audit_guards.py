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
import json
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
        self.patcher_tg = patch("live.telegram.notifier.TelegramNotifier.send_message", return_value=True)
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

    # ─────────────────────────────────────────────────────────────
    # TEST 7: PID LOCK FAIL-CLOSED SAFETY (P0-002)
    # ─────────────────────────────────────────────────────────────
    def test_pid_lock_fail_closed(self):
        trader = LivePortfolioTrader()
        with patch.object(lcfg, "PID_LOCK_FILE", self.test_lock_file):
            with patch("builtins.open", side_effect=PermissionError("Access denied")):
                # When open() raises an error, must fail-closed (return False)
                self.assertFalse(trader._acquire_pid_lock())
                self.assertFalse(trader._lock_acquired)

    # ─────────────────────────────────────────────────────────────
    # TEST 8: BROKER ORDER RECONCILIATION GUARD (NEW-P0-001)
    # ─────────────────────────────────────────────────────────────
    def test_reconcile_broker_orders(self):
        trader = LivePortfolioTrader()

        # Case 1: Broker has an open position matching magic comment
        mock_pos = MagicMock()
        mock_pos.ticket = 88888
        mock_pos.comment = "AsiaMR-FLG"

        trader._order_in_flight["ASIAN"] = True
        with patch.object(trader.connector, "get_open_positions", return_value=[mock_pos]):
            res = trader._reconcile_broker_orders("ASIAN")
            self.assertTrue(res, "Harus mengembalikan True jika posisi aktif ditemukan di broker")
            self.assertTrue(trader.trades_today["ASIAN"], "trades_today harus di-set True jika posisi ditemukan di broker")

        # Case 2: No position at broker
        trader.trades_today["ASIAN"] = False
        with patch.object(trader.connector, "get_open_positions", return_value=[]), \
             patch.object(trader.connector, "get_today_deals", return_value=[]):
            res = trader._reconcile_broker_orders("ASIAN")
            self.assertFalse(res, "Harus mengembalikan False jika order tidak ada di broker")

    # ─────────────────────────────────────────────────────────────
    # TEST 9: DAILY CIRCUIT BREAKER PERSISTENCE (NEW-P1-001)
    # ─────────────────────────────────────────────────────────────
    def test_daily_circuit_breaker_persistence(self):
        import tempfile
        with tempfile.TemporaryDirectory() as temp_dir:
            test_state_file = os.path.join(temp_dir, "test_daily_state.json")
            trader = LivePortfolioTrader()

            with patch.object(trader, "_get_daily_state_path", return_value=test_state_file):
                # 1. Simpan state hari ini
                test_date = date(2026, 9, 20)
                trader.current_trading_day = test_date
                trader.starting_daily_equity = 1000.0
                trader.daily_circuit_breaker_tripped = True
                trader._save_daily_circuit_breaker_state()
                self.assertTrue(os.path.exists(test_state_file))

                with open(test_state_file, "r") as f:
                    data = json.load(f)
                self.assertEqual(data["date"], "2026-09-20")
                self.assertEqual(data["starting_equity"], 1000.0)
                self.assertTrue(data["circuit_breaker_tripped"])

                # 2. Restart di hari yang sama: memuat state tersimpan
                mock_acc = MagicMock()
                mock_acc.equity = 940.0
                with patch.object(trader.connector, "get_account_status", return_value=mock_acc):
                    trader.starting_daily_equity = None
                    trader.daily_circuit_breaker_tripped = False
                    trader._load_or_init_daily_circuit_breaker(test_date)

                    self.assertEqual(trader.starting_daily_equity, 1000.0)
                    self.assertTrue(trader.daily_circuit_breaker_tripped)

                # 3. Hari baru: state di-reset ke ekuitas baru
                tomorrow_date = date(2026, 9, 21)
                mock_acc.equity = 950.0
                with patch.object(trader.connector, "get_account_status", return_value=mock_acc), \
                     patch.object(trader.connector, "get_today_deals", return_value=[]), \
                     patch.object(trader.connector, "get_open_positions", return_value=[]):
                    trader._load_or_init_daily_circuit_breaker(tomorrow_date)
                    self.assertEqual(trader.starting_daily_equity, 950.0)
                    self.assertFalse(trader.daily_circuit_breaker_tripped)

    # ─────────────────────────────────────────────────────────────
    # TEST 10: BROKER TIMEZONE PROBE (P0-003)
    # ─────────────────────────────────────────────────────────────
    def test_probe_broker_timezone(self):
        connector = MT5Connector()
        mock_acc = MagicMock()
        mock_acc.server = "Exness-Real10"

        with patch.object(connector, "get_account_status", return_value=mock_acc), \
             patch.object(lcfg, "BROKER_SERVER_OFFSET_HOURS", 999):
            connector._cached_broker_offset_sec = None
            probe = connector.probe_broker_timezone()
            self.assertEqual(probe["server"], "Exness-Real10")
            self.assertEqual(probe["offset_hours"], 0)
            self.assertEqual(probe["offset_seconds"], 0)
            self.assertIn("now_utc", probe)

    # ─────────────────────────────────────────────────────────────
    # TEST 11: ASIA MR TP STOPS LEVEL SAFEGUARD (P1-006)
    # ─────────────────────────────────────────────────────────────
    def test_asia_mr_tp_stops_level_safeguard(self):
        from engine.asia.signals import Signal, Direction as AsianDirection
        trader = LivePortfolioTrader()
        trader.today_schedule = {
            "ASIAN_START": (0, 0), "ASIAN_END": (23, 59),
            "LONDON_ENTRY_START": (0, 0), "LONDON_ENTRY_END": (23, 59),
            "NY_ENTRY_START": (0, 0), "NY_ENTRY_END": (23, 59)
        }

        # Sinyal BUY dengan TP terlalu dekat (4000.20 saat Ask 4000.00, stop level 0.50)
        sig = Signal(
            bar_index=0,
            datetime=pd.Timestamp.now(timezone.utc),
            direction=AsianDirection.LONG,
            entry_price=4000.0,
            stop_loss=3990.0,
            take_profit=4000.20,
            zscore=-2.5,
            rsi=25.0,
            atr=2.0
        )

        sym_info = MagicMock()
        sym_info.point = 0.01
        sym_info.stops_level = 50  # 50 * 0.01 = 0.50 USD

        df_dummy = pd.DataFrame({
            "datetime": pd.date_range("2026-09-18", periods=100, freq="5min", tz="UTC"),
            "open": [4000.0]*100, "high": [4010.0]*100, "low": [3990.0]*100, "close": [4005.0]*100, "volume": [100]*100
        })

        with patch("live.live_runner.check_asian_entry", return_value=sig), \
             patch("live.live_runner.compute_asian_indicators", return_value=df_dummy), \
             patch.object(trader, "_reconcile_broker_orders", return_value=False), \
             patch.object(trader.connector, "get_symbol_info", return_value=sym_info), \
             patch.object(trader.connector, "open_market_order") as mock_open:

            tick = {"bid": 3999.8, "ask": 4000.0, "spread": 0.2}
            trader._evaluate_asian_mr(df_dummy, datetime.now(timezone.utc), tick, 1000.0)

            # Verifikasi bahwa open_market_order dipanggil dengan tp=None (karena tidak memenuhi stop level)
            mock_open.assert_called_once()
            call_kwargs = mock_open.call_args[1]
            self.assertIsNone(call_kwargs["tp"], "TP harus diubah menjadi None jika melanggar broker stops_level")

    # ─────────────────────────────────────────────────────────────
    # TEST 12: DAILY CIRCUIT BREAKER STRICT FAIL-CLOSED (P1)
    # ─────────────────────────────────────────────────────────────
    def test_daily_circuit_breaker_fail_closed(self):
        trader = LivePortfolioTrader()
        today = date(2026, 9, 20)

        # When get_account_status returns None, must raise RuntimeError, never fallback to 1000
        with patch.object(trader, "_get_daily_state_path", return_value="non_existent_file.json"), \
             patch.object(trader.connector, "get_account_status", return_value=None):
            with self.assertRaises(RuntimeError):
                trader._load_or_init_daily_circuit_breaker(today)

    # ─────────────────────────────────────────────────────────────
    # TEST 13: CONNECTOR DEFENSE-IN-DEPTH INVERTED TP GUARD (P1)
    # ─────────────────────────────────────────────────────────────
    def test_mt5_connector_inverted_tp_guard(self):
        connector = MT5Connector()

        sym_info = MagicMock()
        sym_info.digits = 2
        sym_info.point = 0.01
        sym_info.stops_level = 20  # 0.20 USD

        mock_tick = MagicMock()
        mock_tick.bid = 4000.0
        mock_tick.ask = 4000.2
        mock_tick.time = time.time()

        captured_requests = []
        def capture_order_send(req):
            captured_requests.append(req)
            return MagicMock(retcode=10009, order=111, price=req["price"], volume=req["volume"])

        with patch.object(connector, "is_connected", True), \
             patch.object(connector, "get_symbol_info", return_value=sym_info), \
             patch("live.mt5_connector.mt5.symbol_info_tick", return_value=mock_tick), \
             patch("live.mt5_connector.mt5.order_send", side_effect=capture_order_send), \
             patch.object(lcfg, "DRY_RUN", False):

            # 1. Inverted BUY TP (TP 3990 <= Entry 4000.2)
            connector.open_market_order("BUY", volume=0.1, sl=3990.0, tp=3990.0)
            self.assertNotIn("tp", captured_requests[-1], "Inverted BUY TP harus dihapus dari payload MT5")

            # 2. Inverted SELL TP (TP 4010 >= Entry 4000.0)
            connector.open_market_order("SELL", volume=0.1, sl=4010.0, tp=4010.0)
            self.assertNotIn("tp", captured_requests[-1], "Inverted SELL TP harus dihapus dari payload MT5")

            # 3. BUY TP too close to stops level (TP 4000.30 vs Entry 4000.20, stops_level=0.20 -> min TP 4000.40)
            connector.open_market_order("BUY", volume=0.1, sl=3990.0, tp=4000.30)
            self.assertNotIn("tp", captured_requests[-1], "TP terlalu dekat dengan stops_level harus dihapus dari payload MT5")


if __name__ == "__main__":
    unittest.main()



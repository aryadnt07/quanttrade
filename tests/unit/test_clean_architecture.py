"""
Unit Tests for Clean Architecture, Ports & Adapters, and Intent Protocols
==========================================================================
Verifikasi:
1. Kepatuhan interface IBroker & IStrategy
2. Dataclass OrderIntent & ExitIntent
3. Offline execution testing menggunakan MockBroker
4. Canonical strategy exit evaluation (Asian MR, London ORB, NY ORB)
"""

import unittest
from datetime import datetime, timezone, date
from typing import Optional, List, Dict, Any
import pandas as pd

from src.core.types import (
    Direction,
    ExitReason,
    OrderIntent,
    ExitIntent,
    OrderResult,
    AccountStatus,
)
from src.core.interfaces import IBroker, IStrategy
from src.strategies.asian_mr.signals import evaluate_asian_exit, evaluate_asian_entry
from src.strategies.london_orb.signals import evaluate_london_exit, evaluate_london_entry
from src.strategies.ny_orb.signals import evaluate_ny_exit, evaluate_ny_entry
from src.execution.runner import LivePortfolioTrader
from src.execution.executors.london import LondonLiveStrategy


class MockBroker:
    """Mock implementation of IBroker for 100% offline unit testing."""

    def __init__(self):
        self.connected = True
        self.positions: List[Any] = []
        self.orders: List[Any] = []
        self.closed_tickets: List[int] = []
        self.sent_orders: List[Dict[str, Any]] = []

    def connect(self) -> bool:
        return self.connected

    def get_account_status(self) -> Optional[AccountStatus]:
        return AccountStatus(
            login=12345678,
            server="Mock-Server",
            balance=10000.0,
            equity=10000.0,
            margin=0.0,
            free_margin=10000.0,
            currency="USD",
            trade_allowed=True,
        )

    def get_current_tick(self, symbol: str) -> Optional[Dict[str, Any]]:
        return {
            "bid": 2000.0,
            "ask": 2000.20,
            "spread": 0.20,
            "time": datetime.now(timezone.utc),
        }

    def get_recent_candles(self, symbol: str, timeframe: int, count: int) -> Optional[pd.DataFrame]:
        dates = pd.date_range("2026-09-21 00:00:00", periods=count, freq="5min", tz="UTC")
        return pd.DataFrame({
            "datetime": dates,
            "open": 2000.0,
            "high": 2005.0,
            "low": 1995.0,
            "close": 2002.0,
            "volume": 100,
        })

    def open_market_order(
        self,
        direction: str,
        volume: float,
        sl: float,
        tp: Optional[float] = None,
        comment: str = "",
        symbol: Optional[str] = None,
        magic: Optional[int] = None,
    ) -> OrderResult:
        order_id = len(self.sent_orders) + 1001
        self.sent_orders.append({
            "action": direction,
            "volume": volume,
            "sl": sl,
            "tp": tp,
            "comment": comment,
        })
        return OrderResult(
            success=True,
            retcode=10009,
            order_id=order_id,
            price=2000.0,
            volume=volume,
            comment=f"Mock order {order_id} filled",
        )

    def place_pending_order(
        self,
        order_type: str,
        volume: float,
        price: float,
        sl: float,
        tp: Optional[float] = None,
        comment: str = "",
        symbol: Optional[str] = None,
        magic: Optional[int] = None,
    ) -> OrderResult:
        order_id = len(self.orders) + 2001
        return OrderResult(
            success=True,
            retcode=10009,
            order_id=order_id,
            price=price,
            volume=volume,
            comment=f"Mock pending {order_id} placed",
        )

    def close_position(self, ticket: int, comment: str = "") -> OrderResult:
        self.closed_tickets.append(ticket)
        return OrderResult(
            success=True,
            retcode=10009,
            order_id=ticket,
            price=2000.0,
            volume=0.1,
            comment=f"Mock closed ticket {ticket} ({comment})",
        )

    def cancel_pending_order(self, ticket: int) -> OrderResult:
        return OrderResult(
            success=True,
            retcode=10009,
            order_id=ticket,
            price=0.0,
            volume=0.0,
            comment=f"Mock cancelled {ticket}",
        )

    def get_open_positions(self, symbol: Optional[str] = None) -> List[Any]:
        return self.positions

    def get_open_orders(self, symbol: Optional[str] = None) -> List[Any]:
        return self.orders

    def get_broker_server_utc_offset_seconds(self) -> int:
        return 0

    def get_symbol_info(self, symbol: str) -> Any:
        class SymbolInfo:
            digits = 2
            point = 0.01
            stops_level = 20
        return SymbolInfo()


class MockPosition:
    """Mock position object replicating MT5 TradePosition."""
    def __init__(self, ticket: int, profit: float, comment: str, pos_type: int = 0, open_time: float = 0.0):
        self.ticket = ticket
        self.profit = profit
        self.comment = comment
        self.type = pos_type
        self.time = open_time
        self.price_open = 2000.0
        self.sl = 1990.0
        self.tp = 2020.0
        self.volume = 0.1
        self.magic = 888001
        self.symbol = "XAUUSD"


class TestCleanArchitecture(unittest.TestCase):

    def test_broker_protocol_compliance(self):
        """Uji bahwa MockBroker dan MT5Connector memenuhi protokol IBroker."""
        mock_broker = MockBroker()
        self.assertIsInstance(mock_broker, IBroker)

    def test_order_intent_contracts(self):
        """Uji integritas data model OrderIntent dan ExitIntent."""
        intent = OrderIntent(
            strategy_id="ASIAN",
            action="BUY",
            volume=0.25,
            entry_price=2000.0,
            stop_loss=1990.0,
            take_profit=2010.0,
            comment="AsiaMR-Test",
            magic_number=888001,
        )
        self.assertEqual(intent.strategy_id, "ASIAN")
        self.assertEqual(intent.action, "BUY")
        self.assertEqual(intent.volume, 0.25)

        exit_intent = ExitIntent(
            ticket=99999,
            should_exit=True,
            reason="TP Mean-Reversion",
            comment="TP-Z-Neutral",
            strategy_id="ASIAN",
        )
        self.assertTrue(exit_intent.should_exit)
        self.assertEqual(exit_intent.comment, "TP-Z-Neutral")

    def test_offline_trader_initialization(self):
        """Uji bahwa LivePortfolioTrader dapat di-injeksi dengan MockBroker secara offline."""
        mock_broker = MockBroker()
        trader = LivePortfolioTrader(connector=mock_broker)
        self.assertEqual(trader.connector, mock_broker)
        status = trader.connector.get_account_status()
        self.assertIsNotNone(status)
        self.assertEqual(status.balance, 10000.0)

    def test_canonical_asian_exit_evaluation(self):
        """Uji canonical exit evaluator Asian MR untuk time-stop, hard-cut, dan z-neutral."""
        now_utc = datetime(2026, 9, 21, 3, 0, tzinfo=timezone.utc)

        # 1. Time-stop test (> 60m)
        pos_old = MockPosition(ticket=101, profit=10.0, comment="AsiaMR-FLG", open_time=now_utc.timestamp() - 65 * 60)
        df_dummy = pd.DataFrame({"zscore": [-0.2, -0.2]})
        exit_time = evaluate_asian_exit(
            pos_old, df_dummy, now_utc, broker_utc_offset_sec=0,
            indicator_func=lambda df: df_dummy
        )
        self.assertIsNotNone(exit_time)
        self.assertTrue(exit_time.should_exit)
        self.assertEqual(exit_time.comment, "TimeStop-60m")

        # 2. Hard-cut test (|Z| >= 3.2)
        pos_active = MockPosition(ticket=102, profit=-50.0, comment="AsiaMR-FLG", open_time=now_utc.timestamp() - 20 * 60, pos_type=0)
        df_hardcut = pd.DataFrame({"zscore": [-3.5, -3.5]})
        exit_hc = evaluate_asian_exit(
            pos_active, df_hardcut, now_utc, broker_utc_offset_sec=0,
            indicator_func=lambda df: df_hardcut
        )
        self.assertIsNotNone(exit_hc)
        self.assertTrue(exit_hc.should_exit)
        self.assertEqual(exit_hc.comment, "HardCut-Z3.2")

        # 3. TP Z-Neutral (Z >= -0.5 untuk BUY)
        pos_buy = MockPosition(ticket=103, profit=35.0, comment="AsiaMR-FLG", open_time=now_utc.timestamp() - 20 * 60, pos_type=0)
        df_tp = pd.DataFrame({"zscore": [-0.3, -0.3]})
        exit_tp = evaluate_asian_exit(
            pos_buy, df_tp, now_utc, broker_utc_offset_sec=0,
            indicator_func=lambda df: df_tp
        )
        self.assertIsNotNone(exit_tp)
        self.assertTrue(exit_tp.should_exit)
        self.assertEqual(exit_tp.comment, "TP-Z-Neutral")

    def test_canonical_london_and_ny_cutoffs(self):
        """Uji canonical session cutoff evaluator untuk London ORB dan NY ORB."""
        pos_london = MockPosition(ticket=201, profit=20.0, comment="London-ORB-FLG")
        time_cutoff_london = datetime(2026, 9, 21, 11, 30, tzinfo=timezone.utc)
        exit_lon = evaluate_london_exit(pos_london, time_cutoff_london, cutoff_hm=(11, 25))
        self.assertIsNotNone(exit_lon)
        self.assertTrue(exit_lon.should_exit)
        self.assertEqual(exit_lon.comment, "Cutoff-London")

        pos_ny = MockPosition(ticket=301, profit=15.0, comment="NY-ORB-FLG")
        time_cutoff_ny = datetime(2026, 9, 21, 16, 30, tzinfo=timezone.utc)
        exit_ny = evaluate_ny_exit(pos_ny, time_cutoff_ny, cutoff_hm=(16, 25))
        self.assertIsNotNone(exit_ny)
        self.assertTrue(exit_ny.should_exit)
        self.assertEqual(exit_ny.comment, "Cutoff-NY")

    def test_live_strategy_protocol_conformance(self):
        """Uji bahwa AsiaLiveStrategy, LondonLiveStrategy, dan NYLiveStrategy mematuhi protokol ILiveStrategy."""
        from src.core.interfaces import ILiveStrategy
        from src.execution.executors.asia import AsiaLiveStrategy
        from src.execution.executors.london import LondonLiveStrategy
        from src.execution.executors.ny import NYLiveStrategy

        asia_strat = AsiaLiveStrategy()
        london_strat = LondonLiveStrategy()
        ny_strat = NYLiveStrategy()

        self.assertIsInstance(asia_strat, ILiveStrategy)
        self.assertIsInstance(london_strat, ILiveStrategy)
        self.assertIsInstance(ny_strat, ILiveStrategy)

    def test_dynamic_custom_strategy_injection(self):
        """Uji pembuktian: Strategi ke-4 (Custom Strategy) dapat diinjeksi tanpa mengubah kode LivePortfolioTrader!"""
        from src.core.interfaces import ILiveStrategy

        class DummyGoldScalperStrategy:
            """Strategi ke-4 tiruan yang mematuhi protokol ILiveStrategy."""
            def __init__(self):
                self.strategy_id = "GOLD_SCALPER"
                self.name = "Gold Scalper v1"
                self.trades_today = False
                self.order_in_flight = False
                self.retry_count = 0

            def can_trade(self) -> bool:
                return not self.trades_today

            def on_daily_reset(self, today_date, schedule):
                self.trades_today = False

            def reconcile_broker_orders(self, broker, magic_number):
                return False

            def handle_oco(self, open_positions, open_pendings, broker):
                pass

            def evaluate_entry(self, df_m5, tick, equity, now_utc, schedule, open_pendings=None, broker=None):
                return OrderIntent(
                    strategy_id="GOLD_SCALPER",
                    action="BUY",
                    volume=0.05,
                    entry_price=2000.0,
                    stop_loss=1995.0,
                    take_profit=2010.0,
                    comment="GoldScalper-Test",
                )

            def evaluate_exit(self, position, df_m5, now_utc, broker_utc_offset_sec=0, schedule=None):
                return None

            def on_order_result(self, res, broker=None):
                if res.success:
                    self.trades_today = True

        mock_broker = MockBroker()
        custom_strat = DummyGoldScalperStrategy()

        # Injeksi strategi custom ke LivePortfolioTrader
        trader = LivePortfolioTrader(connector=mock_broker, strategies=[custom_strat])
        self.assertEqual(len(trader.strategies), 1)
        self.assertEqual(trader.strategies[0].strategy_id, "GOLD_SCALPER")

        # Jalankan satu siklus evaluasi tick
        now_utc = datetime(2026, 9, 21, 10, 0, tzinfo=timezone.utc)
        trader.current_trading_day = now_utc.date()
        trader.risk_manager.daily_circuit_breaker_tripped = False
        trader.today_schedule = {}
        # Override active window check untuk pengetesan custom strategi
        trader._is_in_any_active_window = lambda dt: True

        trader._tick_cycle(now_utc)

        # Buktikan bahwa order dieksekusi oleh MockBroker via looping polimorfik!
        self.assertEqual(len(mock_broker.sent_orders), 1)
        sent = mock_broker.sent_orders[0]
        self.assertEqual(sent["action"], "BUY")
        self.assertEqual(sent["volume"], 0.05)
        self.assertIn("GoldScalper-Test", sent["comment"])
        self.assertTrue(custom_strat.trades_today)

    def test_stale_market_data_guard_blocks_execution(self):
        """P2 Protection: Verifikasi bot menolak evaluasi jika feed candle M5 membeku/basi."""
        mock_broker = MockBroker()

        # Buat candle M5 yang berhenti di 10:00:00 UTC (stale)
        stale_end = datetime(2026, 9, 21, 10, 0, tzinfo=timezone.utc)
        dates = pd.date_range(end=stale_end, periods=70, freq="5min", tz="UTC")
        df_stale = pd.DataFrame({
            "datetime": dates,
            "open": 2000.0,
            "high": 2005.0,
            "low": 1995.0,
            "close": 2002.0,
            "volume": 100,
        })
        mock_broker.get_recent_candles = lambda symbol, timeframe, count: df_stale.copy()

        class DummyStrategy:
            strategy_id = "DUMMY"
            name = "Dummy v1"
            trades_today = False
            order_in_flight = False
            retry_count = 0

            def can_trade(self) -> bool:
                return True
            def on_daily_reset(self, today_date, schedule):
                pass
            def reconcile_broker_orders(self, broker, magic_number):
                return False
            def handle_oco(self, open_positions, open_pendings, broker):
                pass
            def evaluate_entry(self, df_m5, tick, equity, now_utc, schedule, open_pendings=None, broker=None):
                return OrderIntent(
                    strategy_id="DUMMY",
                    action="BUY",
                    volume=0.01,
                    entry_price=2000.0,
                    stop_loss=1990.0,
                    take_profit=2010.0,
                    comment="Dummy-Stale-Test",
                )
            def evaluate_exit(self, position, df_m5, now_utc, broker_utc_offset_sec=0, schedule=None):
                return None
            def on_order_result(self, res, broker=None):
                pass

        dummy_strat = DummyStrategy()
        trader = LivePortfolioTrader(connector=mock_broker, strategies=[dummy_strat])

        # Evaluasi saat 10:20:00 UTC (lag = 20 menit = 1200s > max_stale 900s)
        eval_time = datetime(2026, 9, 21, 10, 20, tzinfo=timezone.utc)
        trader.current_trading_day = eval_time.date()
        trader._is_in_any_active_window = lambda dt: True

        res = trader._tick_cycle(eval_time)

        # Harus mengembalikan False dan menolak evaluasi / tidak mengirim order
        self.assertFalse(res)
        self.assertEqual(len(mock_broker.sent_orders), 0)

    def test_stale_market_data_weekend_bypass(self):
        """P2 Protection: Verifikasi guard stale feed tidak memblokir atau alert saat akhir pekan."""
        mock_broker = MockBroker()

        dates = pd.date_range("2026-09-25 21:00:00", periods=70, freq="5min", tz="UTC")
        df_old = pd.DataFrame({
            "datetime": dates,
            "open": 2000.0,
            "high": 2005.0,
            "low": 1995.0,
            "close": 2002.0,
            "volume": 100,
        })
        mock_broker.get_recent_candles = lambda symbol, timeframe, count: df_old.copy()

        trader = LivePortfolioTrader(connector=mock_broker)

        # Evaluasi saat hari Sabtu (2026-09-26 10:00:00 UTC)
        saturday_utc = datetime(2026, 9, 26, 10, 0, tzinfo=timezone.utc)
        self.assertTrue(trader._is_market_closed_weekend(saturday_utc))

        trader._tick_cycle(saturday_utc)
        self.assertFalse(trader._is_feed_stale)

    def test_stale_market_data_telegram_alerts_and_recovery(self):
        """P2 Protection: Verifikasi notifikasi Telegram dikirim saat stale dan saat sembuh (recovery)."""
        mock_broker = MockBroker()

        class MockTelegram:
            is_configured = True
            def __init__(self):
                self.warnings = []
                self.recoveries = []
            def notify_stale_data_warning(self, symbol, lag_minutes, last_candle_time_str, max_allowed_minutes=15.0):
                self.warnings.append((symbol, lag_minutes, last_candle_time_str))
                return True
            def notify_stale_data_recovered(self, symbol, lag_minutes):
                self.recoveries.append((symbol, lag_minutes))
                return True
            def __getattr__(self, name):
                return lambda *args, **kwargs: True

        mock_tele = MockTelegram()
        trader = LivePortfolioTrader(connector=mock_broker, notifier=mock_tele)

        # 1. Feed Stale (lag = 20m)
        stale_end = datetime(2026, 9, 21, 10, 0, tzinfo=timezone.utc)
        dates_stale = pd.date_range(end=stale_end, periods=70, freq="5min", tz="UTC")
        df_stale = pd.DataFrame({
            "datetime": dates_stale,
            "open": 2000.0, "high": 2005.0, "low": 1995.0, "close": 2002.0, "volume": 100,
        })
        mock_broker.get_recent_candles = lambda symbol, timeframe, count: df_stale.copy()

        eval_stale = datetime(2026, 9, 21, 10, 20, tzinfo=timezone.utc)
        trader._tick_cycle(eval_stale)
        self.assertTrue(trader._is_feed_stale)
        self.assertEqual(len(mock_tele.warnings), 1)

        # 2. Feed Recovered (lag = 5m)
        fresh_end = datetime(2026, 9, 21, 10, 20, tzinfo=timezone.utc)
        dates_fresh = pd.date_range(end=fresh_end, periods=70, freq="5min", tz="UTC")
        df_fresh = pd.DataFrame({
            "datetime": dates_fresh,
            "open": 2000.0, "high": 2005.0, "low": 1995.0, "close": 2002.0, "volume": 100,
        })
        mock_broker.get_recent_candles = lambda symbol, timeframe, count: df_fresh.copy()

        eval_fresh = datetime(2026, 9, 21, 10, 25, tzinfo=timezone.utc)
        trader._tick_cycle(eval_fresh)
        self.assertFalse(trader._is_feed_stale)
        self.assertEqual(len(mock_tele.recoveries), 1)

    def test_active_probing_recovers_late_broker_fill(self):
        """P0 Idempotency: Jika order timeout tapi ternyata masuk di broker, probe menyelamatkannya (0 trade hilang, 0 duplikasi)."""
        from unittest.mock import patch
        mock_broker = MockBroker()

        # Simulasikan open_market_order timeout jaringan
        order_calls = []
        def mock_open_market_order(**kwargs):
            order_calls.append(kwargs)
            return OrderResult(False, -10008, 0, 0.0, 0.0, "IPC Timeout: State Unknown")

        mock_broker.open_market_order = mock_open_market_order
        # Posisi ternyata aktif di broker
        mock_broker.get_open_positions = lambda magic: [
            MockPosition(ticket=9991, profit=0.0, comment="London-ORB-FLG-260921")
        ]

        strategy = LondonLiveStrategy()
        trader = LivePortfolioTrader(connector=mock_broker, strategies=[strategy])

        intent = OrderIntent(
            strategy_id="LONDON",
            action="BUY",
            volume=0.05,
            entry_price=2000.0,
            stop_loss=1990.0,
            take_profit=2020.0,
            comment="London-ORB-FLG",
        )

        with patch("src.execution.config.PROBE_TIMEOUT_SEC", 0.02), \
             patch("src.execution.config.PROBE_INTERVAL_SEC", 0.005):
            trader._dispatch_order_intent(strategy, intent)

        # Buktikan: trade berhasil diselamatkan dan tidak ada order ganda yang dikirim!
        self.assertTrue(strategy.trades_today)
        self.assertEqual(strategy.retry_count, 0)
        self.assertEqual(len(order_calls), 1)

    def test_active_probing_clean_broker_triggers_refire(self):
        """P0 Idempotency: Jika order timeout dan broker bersih, bot melakukan Re-Fire (0 trade dikorbankan)."""
        from unittest.mock import patch
        mock_broker = MockBroker()

        order_calls = []
        def mock_open_market_order(**kwargs):
            order_calls.append(kwargs)
            if len(order_calls) == 1:
                return OrderResult(False, -10008, 0, 0.0, 0.0, "IPC Timeout: State Unknown")
            else:
                return OrderResult(True, 10009, 9992, 2000.20, 0.05, "Re-fire filled successfully")

        mock_broker.open_market_order = mock_open_market_order
        mock_broker.get_open_positions = lambda magic: []
        mock_broker.get_today_deals = lambda magic: []

        strategy = LondonLiveStrategy()
        trader = LivePortfolioTrader(connector=mock_broker, strategies=[strategy])

        intent = OrderIntent(
            strategy_id="LONDON",
            action="BUY",
            volume=0.05,
            entry_price=2000.0,
            stop_loss=1990.0,
            take_profit=2020.0,
            comment="London-ORB-FLG",
        )

        with patch("src.execution.config.PROBE_TIMEOUT_SEC", 0.02), \
             patch("src.execution.config.PROBE_INTERVAL_SEC", 0.005):
            trader._dispatch_order_intent(strategy, intent)

        # Buktikan: Re-fire berhasil dieksekusi setelah verifikasi broker bersih
        self.assertTrue(strategy.trades_today)
        self.assertEqual(len(order_calls), 2)
        self.assertEqual(order_calls[1]["direction"], "BUY")

    def test_active_probing_excessive_slippage_aborts_refire(self):
        """P0 Idempotency: Jika harga melompat melebihi toleransi slippage saat timeout, re-fire dibatalkan demi keamanan."""
        from unittest.mock import patch
        mock_broker = MockBroker()

        order_calls = []
        def mock_open_market_order(**kwargs):
            order_calls.append(kwargs)
            return OrderResult(False, -10008, 0, 0.0, 0.0, "IPC Timeout: State Unknown")

        mock_broker.open_market_order = mock_open_market_order
        mock_broker.get_open_positions = lambda magic: []
        mock_broker.get_today_deals = lambda magic: []
        # Harga melompat $5.00 ke 2005.00 (melebihi limit $1.50)
        mock_broker.get_current_tick = lambda symbol: {
            "bid": 2004.80,
            "ask": 2005.00,
            "spread": 0.20,
            "time": datetime.now(timezone.utc),
        }

        strategy = LondonLiveStrategy()
        trader = LivePortfolioTrader(connector=mock_broker, strategies=[strategy])

        intent = OrderIntent(
            strategy_id="LONDON",
            action="BUY",
            volume=0.05,
            entry_price=2000.0,
            stop_loss=1990.0,
            take_profit=2020.0,
            comment="London-ORB-FLG",
        )

        with patch("src.execution.config.PROBE_TIMEOUT_SEC", 0.02), \
             patch("src.execution.config.PROBE_INTERVAL_SEC", 0.005), \
             patch("src.execution.config.MAX_REFIRE_SLIPPAGE_USD", 1.50):
            trader._dispatch_order_intent(strategy, intent)

        # Re-fire dibatalkan, hanya 1 order yang pernah dikirim
        self.assertEqual(len(order_calls), 1)
        self.assertFalse(strategy.trades_today)


if __name__ == "__main__":
    unittest.main()


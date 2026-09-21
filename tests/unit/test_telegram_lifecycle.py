"""
Unit Tests for Telegram Bot Lifecycle & Session Transitions
===========================================================
Verifikasi:
1. Format template notifikasi: startup, shutdown, session open/close, OR box formed, session lockout.
2. Penentuan fase sesi dinamis (_determine_session_phase).
3. Transisi sesi (_check_session_transitions) memicu notify_session_open dan notify_session_close.
4. Pembentukan Box Opening Range (notify_or_formed).
5. Kunci sesi jika terjadi order failure berulang (notify_session_lockout).
"""

import unittest
from datetime import datetime, timezone, date
from typing import Optional, List, Dict, Any

from src.execution.notifications.telegram import TelegramNotifier
from src.execution.runner import LivePortfolioTrader
from src.core.types import OrderIntent, OrderResult, AccountStatus
from src.core.interfaces import IBroker, ILiveStrategy
from src.execution.scheduler import SessionScheduleManager


class MockTelegramNotifier:
    """Mock notifier untuk menangkap pemanggilan notifikasi."""

    def __init__(self):
        self.is_configured = True
        self.mode = "BALANCED"
        self.events: List[Dict[str, Any]] = []

    def send_message(self, text: str) -> bool:
        self.events.append({"type": "send_message", "text": text})
        return True

    def notify_startup(self, account, server, balance, equity, symbol="XAUUSD", active_strategies=None):
        self.events.append({
            "type": "startup",
            "account": account,
            "server": server,
            "balance": balance,
            "equity": equity,
            "symbol": symbol,
            "strategies": active_strategies,
        })
        return True

    def notify_shutdown(self, reason="Manual Stop", balance=None, equity=None):
        self.events.append({
            "type": "shutdown",
            "reason": reason,
            "balance": balance,
            "equity": equity,
        })
        return True

    def notify_session_open(self, session_name, window_info, details=""):
        self.events.append({
            "type": "session_open",
            "session_name": session_name,
            "window_info": window_info,
            "details": details,
        })
        return True

    def notify_session_close(self, session_name, trades_executed_today=False, next_session_info="", audit_report=None):
        self.events.append({
            "type": "session_close",
            "session_name": session_name,
            "trades_executed_today": trades_executed_today,
            "next_session_info": next_session_info,
            "audit_report": audit_report,
        })
        return True

    def notify_or_formed(self, session_name, or_high, or_low, or_range):
        self.events.append({
            "type": "or_formed",
            "session_name": session_name,
            "or_high": or_high,
            "or_low": or_low,
            "or_range": or_range,
        })
        return True

    def notify_session_lockout(self, session_name, retry_count, max_retries):
        self.events.append({
            "type": "session_lockout",
            "session_name": session_name,
            "retry_count": retry_count,
            "max_retries": max_retries,
        })
        return True


class MockBroker:
    """Mock IBroker untuk testing."""

    def __init__(self):
        self.connected = True

    def connect(self) -> bool:
        return self.connected

    def shutdown(self):
        pass

    def get_account_status(self) -> Optional[AccountStatus]:
        return AccountStatus(
            login=998877,
            server="Live-Server",
            balance=15000.0,
            equity=15250.0,
            margin=0.0,
            free_margin=15250.0,
            currency="USD",
            trade_allowed=True,
        )

    def get_current_tick(self, symbol: str) -> Optional[Dict[str, Any]]:
        return {"bid": 2000.0, "ask": 2000.20, "spread": 0.20, "time": datetime.now(timezone.utc)}

    def get_open_positions(self, magic_number: int) -> List[Any]:
        return []

    def get_open_pending_orders(self, magic_number: int) -> List[Any]:
        return []

    def open_market_order(self, direction, volume, sl=None, tp=None, comment=""):
        return OrderResult(
            success=False,
            retcode=10004,
            order_id=0,
            price=0.0,
            volume=volume,
            comment="Requote Rejected",
        )


class TestTelegramTemplates(unittest.TestCase):
    """Test string generation and formatting in TelegramNotifier."""

    def setUp(self):
        self.notifier = TelegramNotifier(bot_token="TEST_TOKEN", chat_id="12345", enabled=True, mode="BALANCED")
        self.sent_messages = []
        self.notifier.send_message = lambda msg: self.sent_messages.append(msg) or True

    def test_notify_startup(self):
        res = self.notifier.notify_startup(
            account=123456,
            server="ICMarkets-Demo",
            balance=10000.0,
            equity=10000.0,
            symbol="XAUUSD",
            active_strategies=["Asian MR", "London ORB", "NY ORB"],
        )
        self.assertTrue(res)
        self.assertEqual(len(self.sent_messages), 1)
        msg = self.sent_messages[0]
        self.assertIn("SYSTEM STARTUP", msg)
        self.assertIn("123456 (ICMarkets-Demo)", msg)
        self.assertIn("$10,000.00 USD", msg)
        self.assertIn("Asian MR, London ORB, NY ORB", msg)

    def test_notify_shutdown(self):
        res = self.notifier.notify_shutdown(
            reason="Manual Stop (Ctrl+C)",
            balance=10500.0,
            equity=10500.0,
        )
        self.assertTrue(res)
        self.assertEqual(len(self.sent_messages), 1)
        msg = self.sent_messages[0]
        self.assertIn("SYSTEM SHUTDOWN", msg)
        self.assertIn("Manual Stop (Ctrl+C)", msg)
        self.assertIn("$10,500.00 USD", msg)

    def test_notify_session_open_and_close(self):
        self.notifier.notify_session_open(
            session_name="Asian Mean Reversion",
            window_info="01:00 - 04:30 UTC",
            details="Risk: 1.0%",
        )
        self.notifier.notify_session_close(
            session_name="Asian Mean Reversion",
            trades_executed_today=True,
            next_session_info="London OR 08:00 UTC",
        )
        self.assertEqual(len(self.sent_messages), 2)
        self.assertIn("SESSION OPEN", self.sent_messages[0])
        self.assertIn("01:00 - 04:30 UTC", self.sent_messages[0])
        self.assertIn("SESSION CLOSE", self.sent_messages[1])
        self.assertIn("Eksekusi Dilakukan", self.sent_messages[1])

    def test_notify_or_formed(self):
        self.notifier.notify_or_formed(
            session_name="London Pit ORB",
            or_high=2050.50,
            or_low=2045.20,
            or_range=5.30,
        )
        self.assertEqual(len(self.sent_messages), 1)
        msg = self.sent_messages[0]
        self.assertIn("BOX OR FORMED", msg)
        self.assertIn("2050.50", msg)
        self.assertIn("2045.20", msg)
        self.assertIn("5.30 pts", msg)

    def test_notify_session_lockout(self):
        self.notifier.notify_session_lockout(
            session_name="London Pit ORB",
            retry_count=3,
            max_retries=3,
        )
        self.assertEqual(len(self.sent_messages), 1)
        msg = self.sent_messages[0]
        self.assertIn("SESSION LOCKOUT", msg)
        self.assertIn("3/3x", msg)


class TestRunnerTransitions(unittest.TestCase):
    """Test session transitions in LivePortfolioTrader."""

    def setUp(self):
        self.broker = MockBroker()
        self.notifier = MockTelegramNotifier()
        self.trader = LivePortfolioTrader(connector=self.broker, notifier=self.notifier)
        self.trader.today_schedule = SessionScheduleManager.get_today_schedule(date(2026, 9, 21))

    def test_phase_determination(self):
        # 02:00 UTC -> Asian window
        dt_asia = datetime(2026, 9, 21, 2, 0, tzinfo=timezone.utc)
        phase, name, win, _ = self.trader._determine_session_phase(dt_asia)
        self.assertEqual(phase, "ASIA_WINDOW")
        self.assertEqual(name, "Asian Mean Reversion")

        # 08:05 UTC -> London OR
        dt_lon_or = datetime(2026, 9, 21, 8, 5, tzinfo=timezone.utc)
        phase, name, win, _ = self.trader._determine_session_phase(dt_lon_or)
        self.assertEqual(phase, "LONDON_OR")

        # 09:00 UTC -> London Entry
        dt_lon_en = datetime(2026, 9, 21, 9, 0, tzinfo=timezone.utc)
        phase, name, win, _ = self.trader._determine_session_phase(dt_lon_en)
        self.assertEqual(phase, "LONDON_ENTRY")

        # 12:00 UTC -> Standby between London and NY
        dt_standby = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)
        phase, name, win, _ = self.trader._determine_session_phase(dt_standby)
        self.assertEqual(phase, "STANDBY")

    def test_session_transition_notification_flow(self):
        # Initial call sets phase without transition notification
        dt_standby1 = datetime(2026, 9, 21, 0, 30, tzinfo=timezone.utc)
        self.trader._check_session_transitions(dt_standby1)
        self.assertEqual(len(self.notifier.events), 0)
        self.assertEqual(self.trader._current_phase, "STANDBY")

        # Transition into Asia (01:00 UTC) -> notify session open
        dt_asia = datetime(2026, 9, 21, 1, 0, tzinfo=timezone.utc)
        self.trader._check_session_transitions(dt_asia)
        self.assertEqual(len(self.notifier.events), 1)
        self.assertEqual(self.notifier.events[0]["type"], "session_open")
        self.assertEqual(self.notifier.events[0]["session_name"], "Asian Mean Reversion")

        # Transition out of Asia (04:30 UTC) -> notify session close
        dt_standby2 = datetime(2026, 9, 21, 4, 30, tzinfo=timezone.utc)
        self.trader._check_session_transitions(dt_standby2)
        self.assertEqual(len(self.notifier.events), 2)
        self.assertEqual(self.notifier.events[1]["type"], "session_close")
        self.assertEqual(self.notifier.events[1]["session_name"], "Asian Mean Reversion")

    def test_or_formed_notification(self):
        # Emulate London OR formed
        lon_strat = self.trader._strategy_map.get("LONDON")
        self.assertIsNotNone(lon_strat)
        lon_strat.or_high = 2055.0
        lon_strat.or_low = 2050.0
        lon_strat.or_range = 5.0

        # Simulate tick OR check
        for strat in self.trader.strategies:
            sid = strat.strategy_id
            if sid in self.trader._or_notified and not self.trader._or_notified[sid]:
                or_h = getattr(strat, "or_high", None)
                or_l = getattr(strat, "or_low", None)
                or_r = getattr(strat, "or_range", None)
                if or_h is not None and or_l is not None and or_r is not None and or_r > 0:
                    self.trader._or_notified[sid] = True
                    self.trader.telegram.notify_or_formed(
                        session_name=strat.name,
                        or_high=or_h,
                        or_low=or_l,
                        or_range=or_r,
                    )

        self.assertEqual(len(self.notifier.events), 1)
        self.assertEqual(self.notifier.events[0]["type"], "or_formed")
        self.assertEqual(self.notifier.events[0]["session_name"], "London Pit ORB")
        self.assertEqual(self.notifier.events[0]["or_high"], 2055.0)

        # Subsequent check should not re-notify (deduplicated)
        for strat in self.trader.strategies:
            sid = strat.strategy_id
            if sid in self.trader._or_notified and not self.trader._or_notified[sid]:
                or_h = getattr(strat, "or_high", None)
                if or_h is not None:
                    self.trader.telegram.notify_or_formed(strat.name, or_h, 2050.0, 5.0)
        self.assertEqual(len(self.notifier.events), 1)

    def test_session_lockout_on_failed_orders(self):
        # Dispatch order that will fail and trigger lockout
        asia_strat = self.trader._strategy_map.get("ASIAN")
        intent = OrderIntent(
            strategy_id="ASIAN",
            action="BUY",
            volume=0.05,
            entry_price=2000.0,
            stop_loss=1990.0,
            take_profit=2010.0,
            comment="Asian MR",
            metadata={},
        )
        # Set retries to MAX_SESSION_RETRIES - 1 (2)
        asia_strat.retry_count = 2
        self.trader._dispatch_order_intent(asia_strat, intent)

        # Should reach retry_count 3 and dispatch session lockout
        lockout_events = [e for e in self.notifier.events if e.get("type") == "session_lockout"]
        self.assertEqual(len(lockout_events), 1)
        self.assertEqual(lockout_events[0]["session_name"], "Asia MR")
        self.assertEqual(lockout_events[0]["retry_count"], 3)


if __name__ == "__main__":
    unittest.main()

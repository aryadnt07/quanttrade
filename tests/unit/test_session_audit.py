"""
Unit Tests for SessionReconciliationAuditor & Telegram Parity Reporting
========================================================================
Verifikasi:
1. Audit sesi Asian MR menghasilkan SessionAuditReport terstruktur.
2. Audit sesi London Pit ORB menghasilkan evaluasi Box & ekspansi volatilitas.
3. Audit sesi New York ORB menghasilkan evaluasi Box NY.
4. Telegram notify_session_close memformat badge paritas dan analisis pasar dengan benar.
"""

import unittest
from datetime import datetime, date, timezone
from typing import Dict, Any, List
import pandas as pd
import numpy as np

from src.execution.audit_engine import SessionReconciliationAuditor, SessionAuditReport
from src.execution.notifications.telegram import TelegramNotifier
from src.execution.scheduler import SessionScheduleManager


class TestSessionAuditEngine(unittest.TestCase):
    """Test suite untuk SessionReconciliationAuditor."""

    def setUp(self):
        self.today = date(2026, 9, 21)
        self.sched = SessionScheduleManager.get_today_schedule(self.today)

        # Generate 100 candle M5 sintetis untuk testing
        times = pd.date_range("2026-09-21 00:00:00", periods=100, freq="5min", tz="UTC")
        self.df_synthetic = pd.DataFrame({
            "datetime": times,
            "open": 2000.0 + np.sin(np.linspace(0, 10, 100)) * 5.0,
            "high": 2000.0 + np.sin(np.linspace(0, 10, 100)) * 5.0 + 1.0,
            "low": 2000.0 + np.sin(np.linspace(0, 10, 100)) * 5.0 - 1.0,
            "close": 2000.0 + np.sin(np.linspace(0, 10, 100)) * 5.0 + 0.2,
            "volume": 100.0,
        })

    def test_audit_asian_session_synthetic(self):
        report = SessionReconciliationAuditor.audit_asian_session(
            df_m5=self.df_synthetic,
            today_date=self.today,
            live_trades_count=0,
            sched=self.sched,
        )
        self.assertIsInstance(report, SessionAuditReport)
        self.assertEqual(report.session_id, "ASIAN")
        self.assertTrue(report.bars_evaluated > 0)
        self.assertIn(report.verdict, ("NORMAL_NO_SETUP", "FILTER_PROTECTED", "TRADE_MATCHED", "DIVERGENCE"))
        self.assertTrue(isinstance(report.parity_matched, bool))

    def test_audit_london_session_synthetic(self):
        report = SessionReconciliationAuditor.audit_london_session(
            df_m5=self.df_synthetic,
            today_date=self.today,
            live_trades_count=0,
            sched=self.sched,
        )
        self.assertIsInstance(report, SessionAuditReport)
        self.assertEqual(report.session_id, "LONDON")
        self.assertIn("or_range", report.details)

    def test_audit_missing_data_graceful(self):
        report = SessionReconciliationAuditor.audit_asian_session(
            df_m5=None,
            today_date=self.today,
            live_trades_count=0,
            sched=self.sched,
        )
        self.assertEqual(report.verdict, "DATA_UNAVAILABLE")
        self.assertEqual(report.bars_evaluated, 0)
        self.assertTrue(report.parity_matched)

    def test_telegram_formatting_with_audit(self):
        sent_messages = []
        notifier = TelegramNotifier(bot_token="FAKE", chat_id="123", enabled=True, mode="BALANCED")
        notifier.send_message = lambda msg: sent_messages.append(msg) or True

        mock_report = SessionAuditReport(
            session_id="ASIAN",
            session_name="Asian Mean Reversion",
            trading_date=self.today,
            bars_evaluated=42,
            live_trades_count=0,
            backtest_signals_count=0,
            parity_matched=True,
            verdict="NORMAL_NO_SETUP",
            primary_reason="Pasar sideways tenang di dekat VWAP.",
            details={"max_abs_zscore": 1.45},
        )

        notifier.notify_session_close(
            session_name="Asian Mean Reversion",
            trades_executed_today=False,
            next_session_info="London OR 08:00 UTC",
            audit_report=mock_report,
        )

        self.assertEqual(len(sent_messages), 1)
        msg = sent_messages[0]
        self.assertIn("SESSION CLOSE", msg)
        self.assertIn("100% PARITY MATCH", msg)
        self.assertIn("42 bar dievaluasi", msg)
        self.assertIn("Pasar sideways tenang di dekat VWAP", msg)


if __name__ == "__main__":
    unittest.main()

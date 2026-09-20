"""
Quantitative Master Portfolio — Institutional Live Execution Runner (MT5)
========================================================================
Master Orchestrator untuk eksekusi live multi-sesi XAU/USD di MetaTrader 5:
1. Asian Mean Reversion (01:00 - 04:30 UTC | Risk: 1.0%)
2. London Pit Opening Range Breakout (08:15 - 11:30 UTC | Risk: 2.0%)
3. New York Opening Range Breakout (Dynamic US DST | Risk: 2.0%)

Modular Architecture:
- live.scheduler (SessionScheduleManager)
- live.risk_manager (RiskManagementMixin, is_process_running)
- live.position_manager (PositionManagementMixin)
- live.executors.asia_executor (AsiaExecutorMixin)
- live.executors.london_executor (LondonExecutorMixin)
- live.executors.ny_executor (NYExecutorMixin)
"""

import sys
import time
import atexit
from datetime import datetime, timezone, date
from typing import Optional, Dict, Any, List

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import pandas as pd
import MetaTrader5 as mt5

from configs import live_config as lcfg
from live.mt5_connector import MT5Connector
from live.telegram import TelegramNotifier
from live.logger import get_logger, disable_quick_edit_mode, TradeJournal

# Mixins & Re-exports
from live.risk_manager import RiskManagementMixin, is_process_running
from live.position_manager import PositionManagementMixin
from live.scheduler import SessionScheduleManager
from live.executors.asia_executor import AsiaExecutorMixin, compute_asian_indicators, check_asian_entry, AsianDirection
from live.executors.london_executor import LondonExecutorMixin
from live.executors.ny_executor import NYExecutorMixin


class LivePortfolioTrader(
    RiskManagementMixin,
    PositionManagementMixin,
    AsiaExecutorMixin,
    LondonExecutorMixin,
    NYExecutorMixin,
):
    """Master Bot Live Trading Orchestrator untuk XAU/USD di MetaTrader 5."""

    def __init__(self):
        self.logger = get_logger()
        self.journal = TradeJournal()
        self.connector = MT5Connector()
        self.telegram = TelegramNotifier()
        self.current_trading_day: Optional[date] = None
        self.today_schedule: Dict[str, Any] = {}
        self.tracked_positions: Dict[int, Dict[str, Any]] = {}
        self.last_daily_heartbeat_day: Optional[date] = None
        self.last_heartbeat_time = 0.0

        # Tracker harian status eksekusi sesi (anti-double trade)
        self.trades_today = {
            "ASIAN": False,
            "LONDON": False,
            "NY": False,
        }

        # In-Flight Order Mutex Lock (Point P0-001 Audit)
        self._order_in_flight = {
            "ASIAN": False,
            "LONDON": False,
            "NY": False,
        }

        # Daily Loss Circuit Breaker
        self.starting_daily_equity: Optional[float] = None
        self.daily_circuit_breaker_tripped: bool = False
        self._lock_acquired: bool = False

        # Tracker retry per sesi (Point #2 Audit: Anti-Requote Spam)
        self.retry_counts = {
            "ASIAN": 0,
            "LONDON": 0,
            "NY": 0,
        }

        # Level Opening Range harian
        self.london_or_high: Optional[float] = None
        self.london_or_low: Optional[float] = None
        self.london_or_range: Optional[float] = None

        self.ny_or_high: Optional[float] = None
        self.ny_or_low: Optional[float] = None
        self.ny_or_range: Optional[float] = None

        # Pelacak Pending Orders OCO (Ticket ID)
        self.pending_orders: Dict[str, List[int]] = {
            "LONDON": [],
            "NY": [],
        }

    # ─────────────────────────────────────────────────────────────
    # STATE SYNC & DAILY RESET
    # ─────────────────────────────────────────────────────────────
    def _sync_state_from_broker(self):
        """Sinkronkan status transaksi hari ini dari broker (Anti-Double Trade saat Restart)."""
        open_pos = self.connector.get_open_positions(lcfg.MAGIC_NUMBER)
        for p in open_pos:
            comm = p.comment or ""
            sess = "Asia MR" if "Asia" in comm else ("London ORB" if "London" in comm else "New York ORB")
            dir_str = "BUY" if p.type == 0 else "SELL"
            risk_usd = abs(p.price_open - p.sl) * p.volume * lcfg.POINT_VALUE if p.sl else 0.0
            self.tracked_positions[p.ticket] = {
                "session": sess,
                "direction": dir_str,
                "volume": p.volume,
                "price_open": p.price_open,
                "sl": p.sl,
                "tp": p.tp,
                "risk_usd": risk_usd,
                "comment": comm,
                "symbol": p.symbol,
            }
            if "AsiaMR" in comm:
                self.trades_today["ASIAN"] = True
            elif "London" in comm:
                self.trades_today["LONDON"] = True
            elif "NY" in comm:
                self.trades_today["NY"] = True

        today_deals = self.connector.get_today_deals(lcfg.MAGIC_NUMBER)
        for d in today_deals:
            comm = d.comment or ""
            if "AsiaMR" in comm:
                self.trades_today["ASIAN"] = True
            elif "London" in comm:
                self.trades_today["LONDON"] = True
            elif "NY" in comm:
                self.trades_today["NY"] = True

        open_pendings = self.connector.get_open_pending_orders(lcfg.MAGIC_NUMBER)
        for o in open_pendings:
            comm = o.comment or ""
            if "London" in comm:
                self.pending_orders["LONDON"].append(o.ticket)
            elif "NY" in comm:
                self.pending_orders["NY"].append(o.ticket)

        status_str = ", ".join([f"{k}: {'DONE' if v else 'READY'}" for k, v in self.trades_today.items()])
        self.logger.info(f"[*] State Recovery Hari Ini -> [{status_str}]")

    def _reset_daily_state_if_needed(self, today_date: date):
        """Reset state, counter, dan hitung ulang jadwal sesi jika tanggal UTC berganti."""
        if self.current_trading_day is None:
            self.current_trading_day = today_date
            self.today_schedule = SessionScheduleManager.get_today_schedule(today_date)
            self._load_or_init_daily_circuit_breaker(today_date)
            return

        if self.current_trading_day != today_date:
            self.current_trading_day = today_date
            self.trades_today = {"ASIAN": False, "LONDON": False, "NY": False}
            self.retry_counts = {"ASIAN": 0, "LONDON": 0, "NY": 0}
            self.london_or_high = None
            self.london_or_low = None
            self.london_or_range = None
            self.ny_or_high = None
            self.ny_or_low = None
            self.ny_or_range = None
            self.pending_orders = {"LONDON": [], "NY": []}
            self._load_or_init_daily_circuit_breaker(today_date)

            self.today_schedule = SessionScheduleManager.get_today_schedule(today_date)
            ny_tz = self.today_schedule.get("NY_TZ_NAME", "UTC")

            self.logger.info(f"[📅 PERGANTIAN HARI UTC] Tanggal baru: {today_date}. Counter trade harian di-reset.")
            self.logger.info(f"   • Jadwal Asia MR  : {self.today_schedule['ASIAN_START'][0]:02d}:{self.today_schedule['ASIAN_START'][1]:02d} - {self.today_schedule['ASIAN_END'][0]:02d}:{self.today_schedule['ASIAN_END'][1]:02d} UTC")
            self.logger.info(f"   • Jadwal London   : OR {self.today_schedule['LONDON_OR_START'][0]:02d}:{self.today_schedule['LONDON_OR_START'][1]:02d} UTC | Entry {self.today_schedule['LONDON_ENTRY_START'][0]:02d}:{self.today_schedule['LONDON_ENTRY_START'][1]:02d} - {self.today_schedule['LONDON_ENTRY_END'][0]:02d}:{self.today_schedule['LONDON_ENTRY_END'][1]:02d} UTC")
            self.logger.info(f"   • Jadwal New York : OR {self.today_schedule['NY_OR_START'][0]:02d}:{self.today_schedule['NY_OR_START'][1]:02d} UTC | Entry {self.today_schedule['NY_ENTRY_START'][0]:02d}:{self.today_schedule['NY_ENTRY_START'][1]:02d} - {self.today_schedule['NY_ENTRY_END'][0]:02d}:{self.today_schedule['NY_ENTRY_END'][1]:02d} UTC ({ny_tz})")

            if self.last_daily_heartbeat_day != today_date:
                self.last_daily_heartbeat_day = today_date
                acc = self.connector.get_account_status()
                if acc:
                    ping = 2.5
                    try:
                        term = mt5.terminal_info()
                        if term and hasattr(term, "ping_last"):
                            ping = float(term.ping_last) / 1000.0
                    except Exception:
                        pass

                    is_wknd = self._is_market_closed_weekend(datetime.now(timezone.utc))
                    next_sess = "Weekend Standby (Market Opens Monday 01:00 UTC)" if is_wknd else "Asian Session (01:00 UTC)"
                    self.telegram.notify_daily_heartbeat(
                        balance=acc.balance,
                        equity=acc.equity,
                        free_margin=acc.free_margin,
                        server=acc.server,
                        latency_ms=ping,
                        next_session=next_sess
                    )

    @staticmethod
    def _is_market_closed_weekend(now_utc: datetime) -> bool:
        """Deteksi apakah pasar XAU/USD sedang tutup di akhir pekan."""
        wd = now_utc.weekday()
        if wd == 4 and now_utc.hour >= 22:
            return True
        if wd == 5:
            return True
        if wd == 6 and now_utc.hour < 22:
            return True
        return False

    def _weekend_standby_cycle(self, now_utc: datetime):
        """Siklus hibernasi akhir pekan (ultra hemat CPU)."""
        today_date = now_utc.date()
        self._reset_daily_state_if_needed(today_date)

        curr_time_sec = time.time()
        if curr_time_sec - self.last_heartbeat_time >= 1800.0 or self.last_heartbeat_time == 0.0:
            self.last_heartbeat_time = curr_time_sec
            day_name = now_utc.strftime("%A")
            self.logger.info(f"[😴 WEEKEND STANDBY] Pasar {lcfg.SYMBOL} tutup ({day_name}). Bot hibernasi hemat CPU (Next: Senin 01:00 UTC).")

    def _is_in_any_active_window(self, now_utc: datetime) -> bool:
        """Cek apakah saat ini berada dalam jendela entri aktif."""
        hm = (now_utc.hour, now_utc.minute)
        sched = self.today_schedule
        if sched.get("ASIAN_START") and sched["ASIAN_START"] <= hm < sched["ASIAN_END"]:
            return True
        if sched.get("LONDON_ENTRY_START") and sched["LONDON_ENTRY_START"] <= hm < sched["LONDON_ENTRY_END"]:
            return True
        if sched.get("NY_ENTRY_START") and sched["NY_ENTRY_START"] <= hm < sched["NY_ENTRY_END"]:
            return True
        return False

    def _get_active_session_name(self, now_utc: datetime) -> str:
        """Deteksi nama sesi trading saat ini."""
        hm = (now_utc.hour, now_utc.minute)
        sched = self.today_schedule
        if sched.get("ASIAN_START") and sched["ASIAN_START"] <= hm < sched["ASIAN_END"]:
            return "Asia MR"
        elif sched.get("LONDON_ENTRY_START") and sched["LONDON_ENTRY_START"] <= hm < sched["LONDON_ENTRY_END"]:
            return "London Pit ORB"
        elif sched.get("NY_ENTRY_START") and sched["NY_ENTRY_START"] <= hm < sched["NY_ENTRY_END"]:
            return f"New York ORB ({sched.get('NY_TZ_NAME', 'UTC')})"
        return "Di Luar Jendela Trading"

    def _tick_cycle(self, now_utc: Optional[datetime] = None) -> bool:
        """Siklus evaluasi pasar tiap tick."""
        if now_utc is None:
            now_utc = datetime.now(timezone.utc)
        today_date = now_utc.date()
        self._reset_daily_state_if_needed(today_date)

        tick = self.connector.get_tick(lcfg.SYMBOL)
        if not tick:
            return False

        df_m5 = self.connector.get_live_rates(symbol=lcfg.SYMBOL, timeframe=mt5.TIMEFRAME_M5, count=200)
        if df_m5 is None or len(df_m5) < 65:
            return False

        curr_time_sec = time.time()
        if curr_time_sec - self.last_heartbeat_time >= 60.0:
            self.last_heartbeat_time = curr_time_sec
            active_session = self._get_active_session_name(now_utc)
            self.logger.info(f"Heartbeat | Bid: {tick['bid']:.2f} | Ask: {tick['ask']:.2f} | Spread: ${tick['spread']:.2f} | Sesi: {active_session}")

        # 1. KELOLA POSISI AKTIF & PENDING ORDERS OCO
        open_positions = self.connector.get_open_positions(lcfg.MAGIC_NUMBER)
        open_pendings = self.connector.get_open_pending_orders(lcfg.MAGIC_NUMBER)

        self._track_and_notify_positions(open_positions)

        if open_positions and open_pendings:
            self._handle_oco_cancellation(open_positions, open_pendings)

        if open_positions:
            self._manage_open_positions(open_positions, df_m5, now_utc)

        # Cek Daily Loss Circuit Breaker
        acc = self.connector.get_account_status()
        if acc:
            self._check_daily_circuit_breaker(acc.equity, today_date)

        # 2. EVALUASI SINYAL ENTRI BARU
        is_in_active_window = self._is_in_any_active_window(now_utc)
        if len(open_positions) < lcfg.MAX_OPEN_TRADES and not self.daily_circuit_breaker_tripped:
            equity = acc.equity if acc else 1000.0
            self._evaluate_asian_mr(df_m5, now_utc, tick, equity)
            self._evaluate_london_orb(df_m5, now_utc, tick, equity, open_pendings)
            self._evaluate_ny_orb(df_m5, now_utc, tick, equity, open_pendings)

        return is_in_active_window

    def start(self):
        """Memulai loop eksekusi live bot."""
        if not self._acquire_pid_lock():
            sys.exit(1)
        atexit.register(self._release_pid_lock)

        if getattr(lcfg, "DISABLE_QUICK_EDIT", True):
            if disable_quick_edit_mode():
                self.logger.info("[🛡️ QUICK-EDIT PROTECTION] QuickEdit Mode dinonaktifkan (Terminal kebal freeze mouse).")

        tg_status = f"ON ({self.telegram.mode} - Option A)" if self.telegram.is_configured else "OFF"
        banner = (
            f"\n{'=' * 76}\n"
            f"   QUANTITATIVE MASTER PORTFOLIO — INSTITUTIONAL LIVE TRADER (MT5)\n"
            f"   Simbol: {lcfg.SYMBOL} | Magic: {lcfg.MAGIC_NUMBER}\n"
            f"   Mode Eksekusi Breakout : [{lcfg.BREAKOUT_EXECUTION_MODE}]\n"
            f"   Dynamic DST Tracking   : [{'ON (Wall Street Local Time)' if lcfg.USE_DYNAMIC_DST else 'OFF'}]\n"
            f"   Mode Trading           : {'[DRY RUN - SIMULASI]' if lcfg.DRY_RUN else '[REAL ORDER EXECUTION]'}\n"
            f"   Telegram Notifier      : [{tg_status}]\n"
            f"   Dual Logging           : [ON -> File: {getattr(lcfg, 'LOG_DIR', 'logs')} | Retensi: {getattr(lcfg, 'LOG_BACKUP_COUNT_DAYS', 30)} hari]\n"
            f"   Trade Journal CSV      : [ON -> {getattr(lcfg, 'TRADE_JOURNAL_FILE', 'logs/live_trade_journal.csv')}]\n"
            f"{'=' * 76}\n"
        )
        print(banner)
        self.logger.info("Bot Live Execution Engine diinisialisasi.")

        if not self.connector.connect():
            self.logger.error("[X] GAGAL: Tidak dapat terhubung ke MetaTrader 5. Pastikan MT5 terbuka dan login.")
            self.telegram.notify_critical_alert("Koneksi MT5 Gagal", "Bot tidak dapat terhubung ke terminal MetaTrader 5.")
            sys.exit(1)


        acc = self.connector.get_account_status()
        if acc:
            self.logger.info(f"[✓] Terhubung ke Akun : {acc.login} ({acc.server})")
            self.logger.info(f"    Saldo Akun        : ${acc.balance:,.2f} {acc.currency}")
            self.logger.info(f"    Ekuitas Akun      : ${acc.equity:,.2f} {acc.currency}")
            self.logger.info(f"    Margin Bebas      : ${acc.free_margin:,.2f} {acc.currency}")

            if not acc.trade_allowed:
                warn_msg = (
                    "\n" + "!" * 76 + "\n"
                    "  [⚠️ PERINGATAN PENTING] FITUR 'ALGO TRADING' DI MT5 SAAT INI NONAKTIF!\n"
                    "  Silakan KLIK tombol 'Algo Trading' pada toolbar MT5 hingga berwarna HIJAU.\n"
                    "!" * 76 + "\n"
                )
                print(warn_msg)
                self.logger.warning("[⚠️ ALGO TRADING DISABLED] Tombol 'Algo Trading' di terminal MT5 belum aktif!")

            if self.telegram.is_configured:
                self.telegram.send_message(
                    f"<b>🚀 [SYSTEM STARTUP] QuantTrade 24/7 Engine</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"Bot live execution telah aktif di Windows VPS.\n"
                    f"• <b>Akun:</b> <code>{acc.login} ({acc.server})</code>\n"
                    f"• <b>Saldo:</b> <code>${acc.balance:,.2f} USD</code>\n"
                    f"• <b>Mode:</b> <code>{self.telegram.mode} (Option A)</code>\n"
                    f"• <b>Simbol:</b> <code>{lcfg.SYMBOL}</code>\n"
                    f"• <b>Waktu:</b> <code>{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}</code>"
                )

        today_utc = datetime.now(timezone.utc).date()
        self.current_trading_day = today_utc
        self.today_schedule = SessionScheduleManager.get_today_schedule(today_utc)
        self._load_or_init_daily_circuit_breaker(today_utc)
        self._sync_state_from_broker()

        self.logger.info("[*] Memulai loop pemantauan pasar real-time (Tekan Ctrl+C untuk stop)...")

        try:
            while True:
                now_utc = datetime.now(timezone.utc)

                if self._is_market_closed_weekend(now_utc):
                    self._weekend_standby_cycle(now_utc)
                    time.sleep(60.0)
                    continue

                is_active_window = self._tick_cycle(now_utc)
                sleep_duration = lcfg.POLL_INTERVAL_FAST_SEC if is_active_window else lcfg.POLL_INTERVAL_IDLE_SEC
                time.sleep(sleep_duration)
        except KeyboardInterrupt:
            self.logger.info("\n[!] Perintah berhenti diterima. Mematikan bot...")
        except Exception as e:
            err_msg = f"Runtime loop exception: {str(e)}"
            self.logger.critical(f"\n[💥 CRITICAL EXCEPTION] {err_msg}")
            self.telegram.notify_critical_alert("Runtime Exception", err_msg)
            raise e
        finally:
            self.connector.shutdown()
            self._release_pid_lock()
            self.logger.info("[✓] Koneksi MT5 ditutup dengan aman. Bot berhenti.")


if __name__ == "__main__":
    bot = LivePortfolioTrader()
    bot.start()

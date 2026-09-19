"""
Quantitative Master Portfolio — Institutional Live Execution Runner (MT5)
========================================================================
Runner trading live otomatis multi-sesi terpadu untuk XAU/USD di MetaTrader 5:
1. Asian Mean Reversion (01:00 - 04:30 UTC | Risk: 1.0%)
2. London Pit Opening Range Breakout (08:15 - 11:30 UTC | Risk: 2.0%)
3. New York Opening Range Breakout (Dynamic US DST | Risk: 2.0%)

Arsitektur Kepatuhan Audit Red Team (audit_report_live_connector.md):
- [✓] Point 1: Low-Latency Polling (100ms) & Pending Stop OCO Engine
- [✓] Point 2: Anti-Spam / Requote Lockout Guard (Max 3 Retries, no infinite loop)
- [✓] Point 3: Anti-Chasing Price Ceiling ($0.40 max breakout slippage)
- [✓] Point 4: Dynamic Daylight Saving Time (DST) Tracking via zoneinfo (America/New_York)
- [✓] AutoTrading Disabled Warning (Retcode 10027 proactive detection)
- [✓] State Recovery on Restart (Anti-double trade)
"""

import os
import sys
import time
from datetime import datetime, timezone, date
from zoneinfo import ZoneInfo
from typing import Optional, Dict, Any, List

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, ".")

import numpy as np
import pandas as pd
import MetaTrader5 as mt5

from live.mt5_connector import MT5Connector, translate_retcode
from live import live_config as lcfg
from live.telegram import TelegramNotifier
from live.logger import get_logger, disable_quick_edit_mode, TradeJournal

# Indikator dan Logika Sinyal Asia
from engine.asia.indicators import compute_all as compute_asian_indicators
from engine.asia.signals import (
    check_entry_signal as check_asian_entry,
    Direction as AsianDirection,
)


class SessionScheduleManager:
    """Pengelola jadwal sesi dinamis dengan dukungan Daylight Saving Time (DST)."""

    @staticmethod
    def get_today_schedule(today_utc_date: date) -> Dict[str, Any]:
        schedule = {}

        # 1. Asian Session (Tokyo/Singapore — No DST, UTC Statis)
        schedule["ASIAN_START"] = lcfg.ASIAN_START_TIME
        schedule["ASIAN_END"] = lcfg.ASIAN_END_TIME
        schedule["ASIAN_CUTOFF"] = lcfg.ASIAN_CUTOFF_TIME

        # 2. London Session
        if getattr(lcfg, "USE_LONDON_LOCAL_TIME", False):
            lon_tz = ZoneInfo("Europe/London")
            dt_lon_or = datetime(today_utc_date.year, today_utc_date.month, today_utc_date.day, 8, 0, tzinfo=lon_tz).astimezone(timezone.utc)
            dt_lon_en = datetime(today_utc_date.year, today_utc_date.month, today_utc_date.day, 8, 15, tzinfo=lon_tz).astimezone(timezone.utc)
            dt_lon_co = datetime(today_utc_date.year, today_utc_date.month, today_utc_date.day, 11, 25, tzinfo=lon_tz).astimezone(timezone.utc)
            schedule["LONDON_OR_START"] = (dt_lon_or.hour, dt_lon_or.minute)
            schedule["LONDON_ENTRY_START"] = (dt_lon_en.hour, dt_lon_en.minute)
            schedule["LONDON_CUTOFF"] = (dt_lon_co.hour, dt_lon_co.minute)
        else:
            schedule["LONDON_OR_START"] = lcfg.LONDON_OR_START
            schedule["LONDON_ENTRY_START"] = lcfg.LONDON_ENTRY_START
            schedule["LONDON_CUTOFF"] = lcfg.LONDON_CUTOFF_TIME

        schedule["LONDON_ENTRY_END"] = lcfg.LONDON_ENTRY_END

        # 3. New York Session (Wall Street Open 09:30 AM America/New_York — DST Dynamic)
        if getattr(lcfg, "USE_DYNAMIC_DST", True):
            ny_tz = ZoneInfo("America/New_York")
            dt_ny_or = datetime(today_utc_date.year, today_utc_date.month, today_utc_date.day, 9, 30, tzinfo=ny_tz).astimezone(timezone.utc)
            dt_ny_en = datetime(today_utc_date.year, today_utc_date.month, today_utc_date.day, 9, 45, tzinfo=ny_tz).astimezone(timezone.utc)
            dt_ny_end = datetime(today_utc_date.year, today_utc_date.month, today_utc_date.day, 12, 30, tzinfo=ny_tz).astimezone(timezone.utc)
            dt_ny_co = datetime(today_utc_date.year, today_utc_date.month, today_utc_date.day, 12, 25, tzinfo=ny_tz).astimezone(timezone.utc)

            schedule["NY_OR_START"] = (dt_ny_or.hour, dt_ny_or.minute)
            schedule["NY_ENTRY_START"] = (dt_ny_en.hour, dt_ny_en.minute)
            schedule["NY_ENTRY_END"] = (dt_ny_end.hour, dt_ny_end.minute)
            schedule["NY_CUTOFF"] = (dt_ny_co.hour, dt_ny_co.minute)
            schedule["NY_TZ_NAME"] = dt_ny_or.tzname()
        else:
            schedule["NY_OR_START"] = lcfg.NY_OR_START
            schedule["NY_ENTRY_START"] = lcfg.NY_ENTRY_START
            schedule["NY_ENTRY_END"] = lcfg.NY_ENTRY_END
            schedule["NY_CUTOFF"] = lcfg.NY_CUTOFF_TIME
            schedule["NY_TZ_NAME"] = "STATIC_UTC"

        return schedule


class LivePortfolioTrader:
    """Master Bot Live Trading untuk XAU/USD di MetaTrader 5."""

    def __init__(self):
        self.logger = get_logger()
        self.journal = TradeJournal()
        self.connector = MT5Connector()
        self.telegram = TelegramNotifier()
        self.current_trading_day: Optional[date] = None
        self.today_schedule: Dict[str, Any] = {}
        self.tracked_positions: Dict[int, Dict[str, Any]] = {}
        self.last_daily_heartbeat_day: Optional[date] = None

        # Tracker harian status eksekusi sesi (anti-double trade)
        self.trades_today = {
            "ASIAN": False,
            "LONDON": False,
            "NY": False,
        }

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

        self.last_heartbeat_time = 0.0

    def start(self):
        """Memulai loop eksekusi live bot."""
        # Proteksi QuickEdit Mode di Windows agar terminal tidak freeze saat diklik
        if getattr(lcfg, "DISABLE_QUICK_EDIT", True):
            if disable_quick_edit_mode():
                self.logger.info("[🛡️ QUICK-EDIT PROTECTION] QuickEdit Mode dinonaktifkan (Terminal kebal dari freeze klik mouse).")

        tg_status = f"ON ({self.telegram.mode} - Option A)" if self.telegram.is_configured else "OFF"
        banner = (
            "\n" + "=" * 76 + "\n"
            "   QUANTITATIVE MASTER PORTFOLIO — INSTITUTIONAL LIVE TRADER (MT5)\n"
            f"   Simbol: {lcfg.SYMBOL} | Magic: {lcfg.MAGIC_NUMBER}\n"
            f"   Mode Eksekusi Breakout : [{lcfg.BREAKOUT_EXECUTION_MODE}]\n"
            f"   Dynamic DST Tracking   : [{'ON (Wall Street Local Time)' if lcfg.USE_DYNAMIC_DST else 'OFF'}]\n"
            f"   Mode Trading           : {'[DRY RUN - SIMULASI]' if lcfg.DRY_RUN else '[REAL ORDER EXECUTION]'}\n"
            f"   Telegram Notifier      : [{tg_status}]\n"
            f"   Dual Logging           : [ON -> File: {getattr(lcfg, 'LOG_DIR', 'logs')} | Retensi: {getattr(lcfg, 'LOG_BACKUP_COUNT_DAYS', 30)} hari]\n"
            f"   Trade Journal CSV      : [ON -> {getattr(lcfg, 'TRADE_JOURNAL_FILE', 'logs/live_trade_journal.csv')}]\n"
            "=" * 76 + "\n"
        )
        print(banner)
        self.logger.info("Bot Live Execution Engine diinisialisasi.")

        if not self.connector.connect():
            self.logger.error("[X] GAGAL: Tidak dapat terhubung ke MetaTrader 5. Pastikan MT5 terbuka dan login.")
            self.telegram.notify_critical_alert("Koneksi MT5 Gagal", "Bot tidak dapat terhubung ke terminal MetaTrader 5.")
            return

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
                    "  Silakan KLIK tombol 'Algo Trading' pada toolbar atas terminal MT5 Anda\n"
                    "  hingga ikon berubah menjadi HIJAU agar order dapat dikirim.\n"
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

        # Inisialisasi jadwal sesi hari ini sebelum sinkronisasi status
        today_utc = datetime.now(timezone.utc).date()
        self.current_trading_day = today_utc
        self.today_schedule = SessionScheduleManager.get_today_schedule(today_utc)

        # Sinkronkan status transaksi hari ini dari broker (Anti-Double Trade saat Restart/Crash)
        self._sync_state_from_broker()

        self.logger.info("[*] Memulai loop pemantauan pasar real-time (Tekan Ctrl+C untuk stop)...")

        try:
            while True:
                now_utc = datetime.now(timezone.utc)

                # ── WEEKEND STANDBY MODE (HEMAT CPU & ZERO TICK POLLING) ──
                if self._is_market_closed_weekend(now_utc):
                    self._weekend_standby_cycle(now_utc)
                    time.sleep(60.0)  # Tidur 60 detik (ultra hemat CPU saat market tutup)
                    continue

                is_active_window = self._tick_cycle(now_utc)
                # Latensi Rendah: Polling 100ms saat di jendela breakout, 1.0s saat idle (Point #1 Audit)
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
            self.logger.info("[✓] Koneksi MT5 ditutup dengan aman. Bot berhenti.")

    def _sync_state_from_broker(self):
        """Sinkronkan status transaksi hari ini agar aman saat bot di-restart."""
        # 1. Cek posisi terbuka dan sinkronkan tracker posisi
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

        # 2. Cek transaksi yang sudah selesai hari ini (History Deals MT5)
        today_deals = self.connector.get_today_deals(lcfg.MAGIC_NUMBER)
        for d in today_deals:
            comm = d.comment or ""
            if "AsiaMR" in comm:
                self.trades_today["ASIAN"] = True
            elif "London" in comm:
                self.trades_today["LONDON"] = True
            elif "NY" in comm:
                self.trades_today["NY"] = True

        # 3. Cek pending orders aktif (jika mode Breakout PENDING_STOP_OCO)
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
            # Startup awal: inisialisasi tanggal tanpa me-reset state yang baru di-sync
            self.current_trading_day = today_date
            self.today_schedule = SessionScheduleManager.get_today_schedule(today_date)
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

            # Hitung jadwal sesi hari ini dengan DST dinamis (Point #4 Audit)
            self.today_schedule = SessionScheduleManager.get_today_schedule(today_date)
            ny_tz = self.today_schedule.get("NY_TZ_NAME", "UTC")

            self.logger.info(f"[📅 PERGANTIAN HARI UTC] Tanggal baru: {today_date}. Counter trade harian di-reset.")
            self.logger.info(f"   • Jadwal Asia MR  : {self.today_schedule['ASIAN_START'][0]:02d}:{self.today_schedule['ASIAN_START'][1]:02d} - {self.today_schedule['ASIAN_END'][0]:02d}:{self.today_schedule['ASIAN_END'][1]:02d} UTC")
            self.logger.info(f"   • Jadwal London   : OR {self.today_schedule['LONDON_OR_START'][0]:02d}:{self.today_schedule['LONDON_OR_START'][1]:02d} UTC | Entry {self.today_schedule['LONDON_ENTRY_START'][0]:02d}:{self.today_schedule['LONDON_ENTRY_START'][1]:02d} - {self.today_schedule['LONDON_ENTRY_END'][0]:02d}:{self.today_schedule['LONDON_ENTRY_END'][1]:02d} UTC")
            self.logger.info(f"   • Jadwal New York : OR {self.today_schedule['NY_OR_START'][0]:02d}:{self.today_schedule['NY_OR_START'][1]:02d} UTC | Entry {self.today_schedule['NY_ENTRY_START'][0]:02d}:{self.today_schedule['NY_ENTRY_START'][1]:02d} - {self.today_schedule['NY_ENTRY_END'][0]:02d}:{self.today_schedule['NY_ENTRY_END'][1]:02d} UTC ({ny_tz})")

            # Kirim Daily Heartbeat Telegram 1x sehari jam 00:00 UTC (Option A)
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
        """Deteksi apakah pasar XAU/USD sedang tutup di akhir pekan.

        Jadwal Pasar XAU/USD:
        - Tutup        : Jumat pukul 22:00 UTC (Sabtu 05:00 WIB)
        - Buka Kembali : Minggu pukul 22:00 UTC (Senin 05:00 WIB)
        """
        wd = now_utc.weekday()
        # Jumat malam setelah 22:00 UTC
        if wd == 4 and now_utc.hour >= 22:
            return True
        # Sabtu seharian penuh
        if wd == 5:
            return True
        # Minggu sebelum jam 22:00 UTC
        if wd == 6 and now_utc.hour < 22:
            return True
        return False

    def _weekend_standby_cycle(self, now_utc: datetime):
        """Siklus hibernasi akhir pekan (ultra hemat CPU, zero MT5 tick polling)."""
        today_date = now_utc.date()
        self._reset_daily_state_if_needed(today_date)

        curr_time_sec = time.time()
        # Cetak log setiap 30 menit sekali agar terminal bersih dan tidak spam
        if curr_time_sec - self.last_heartbeat_time >= 1800.0 or self.last_heartbeat_time == 0.0:
            self.last_heartbeat_time = curr_time_sec
            day_name = now_utc.strftime("%A")
            self.logger.info(f"[😴 WEEKEND STANDBY] Pasar {lcfg.SYMBOL} tutup ({day_name}). Bot hibernasi hemat CPU (Next: Senin 01:00 UTC).")

    def _tick_cycle(self, now_utc: Optional[datetime] = None) -> bool:
        """Siklus evaluasi pasar. Mengembalikan True jika berada dalam jendela aktif."""
        if now_utc is None:
            now_utc = datetime.now(timezone.utc)
        today_date = now_utc.date()
        self._reset_daily_state_if_needed(today_date)

        tick = self.connector.get_tick(lcfg.SYMBOL)
        if not tick:
            return False

        # Ambil 200 bar M5 (cukup untuk warm-up ATR SMA50 dan identifikasi box OR)
        df_m5 = self.connector.get_live_rates(symbol=lcfg.SYMBOL, timeframe=mt5.TIMEFRAME_M5, count=200)
        if df_m5 is None or len(df_m5) < 65:
            return False

        # Heartbeat log berkala setiap 60 detik
        curr_time_sec = time.time()
        if curr_time_sec - self.last_heartbeat_time >= 60.0:
            self.last_heartbeat_time = curr_time_sec
            active_session = self._get_active_session_name(now_utc)
            self.logger.info(f"Heartbeat | Bid: {tick['bid']:.2f} | Ask: {tick['ask']:.2f} | Spread: ${tick['spread']:.2f} | Sesi: {active_session}")

        # 1. KELOLA POSISI AKTIF & PENDING ORDERS OCO
        open_positions = self.connector.get_open_positions(lcfg.MAGIC_NUMBER)
        open_pendings = self.connector.get_open_pending_orders(lcfg.MAGIC_NUMBER)

        # Audit & Notifikasi Telegram (Entry & Exit Tracking - Option A)
        self._track_and_notify_positions(open_positions)

        # OCO Logic: Jika ada posisi yang sudah terisi, batalkan sisa pending order yang belum terisi
        if open_positions and open_pendings:
            self._handle_oco_cancellation(open_positions, open_pendings)

        # Kelola penutupan posisi aktif (TP Z-neutral, Session Cutoff)
        if open_positions:
            self._manage_open_positions(open_positions, df_m5, now_utc)

        # 2. EVALUASI SINYAL ENTRI BARU
        is_in_active_window = self._is_in_any_active_window(now_utc)
        if len(open_positions) < lcfg.MAX_OPEN_TRADES:
            acc = self.connector.get_account_status()
            equity = acc.equity if acc else 1000.0

            # Evaluasi Modul 1: Asia Mean Reversion
            self._evaluate_asian_mr(df_m5, now_utc, tick, equity)

            # Evaluasi Modul 2: London Pit ORB
            self._evaluate_london_orb(df_m5, now_utc, tick, equity, open_pendings)

            # Evaluasi Modul 3: New York ORB
            self._evaluate_ny_orb(df_m5, now_utc, tick, equity, open_pendings)

        return is_in_active_window

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

    # ─────────────────────────────────────────────────────────────
    # TELEGRAM AUDIT & NOTIFIKASI POSISI (OPTION A: BALANCED MODE)
    # ─────────────────────────────────────────────────────────────
    def _track_and_notify_positions(self, current_open_positions: list):
        """Pantau posisi baru untuk notifikasi Entry, dan deteksi penutupan untuk notifikasi Exit."""
        current_tickets = set()

        # 1. Deteksi posisi baru (Entry)
        for p in current_open_positions:
            ticket = p.ticket
            current_tickets.add(ticket)
            if ticket not in self.tracked_positions:
                comm = p.comment or ""
                sess = "Asia MR" if "Asia" in comm else ("London ORB" if "London" in comm else "New York ORB")
                dir_str = "BUY" if p.type == mt5.ORDER_TYPE_BUY else "SELL"
                risk_usd = abs(p.price_open - p.sl) * p.volume * lcfg.POINT_VALUE if p.sl else 0.0

                self.tracked_positions[ticket] = {
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

                # Kirim notifikasi Telegram saat posisi terisi (Entry)
                self.telegram.notify_entry(
                    session=sess,
                    direction=dir_str,
                    volume=p.volume,
                    price=p.price_open,
                    sl=p.sl,
                    tp=p.tp,
                    risk_usd=risk_usd,
                    ticket=ticket,
                    symbol=p.symbol,
                )

                # Catat ke Trade Journal CSV & File Log
                self.journal.record_entry(
                    session=sess,
                    ticket=ticket,
                    action=dir_str,
                    volume=p.volume,
                    open_price=p.price_open,
                    sl=p.sl,
                    tp=p.tp,
                    slippage_pts=0.0,
                    comment=comm,
                )
                self.logger.info(f"[🚀 POSISI TERISI] {sess} {dir_str} {p.volume:.2f} Lot @ {p.price_open:.3f} | Ticket: {ticket} | SL: {p.sl:.3f} | TP: {p.tp:.3f}")

        # 2. Deteksi posisi yang baru saja ditutup (Exit)
        closed_tickets = [t for t in list(self.tracked_positions.keys()) if t not in current_tickets]
        for ticket in closed_tickets:
            info = self.tracked_positions[ticket]
            deals = mt5.history_deals_get(position=ticket)
            exit_price = info["price_open"]
            pnl_usd = 0.0
            reason = "Position Closed"

            if deals:
                exit_deals = [d for d in deals if d.entry == 1]
                if exit_deals:
                    last_deal = exit_deals[-1]
                    exit_price = last_deal.price
                    pnl_usd = last_deal.profit
                    deal_comm = (last_deal.comment or "").lower()
                    if "[tp" in deal_comm or "tp" in deal_comm:
                        reason = "Target Hit (TP)"
                    elif "[sl" in deal_comm or "sl" in deal_comm:
                        reason = "Stop Loss (SL)"
                    elif "cutoff" in deal_comm:
                        reason = f"Session Cutoff ({last_deal.comment})"
                    elif "z-neutral" in deal_comm:
                        reason = "Z-Neutral Mean Reversion"
                    else:
                        reason = last_deal.comment or "Position Closed"

            r_mult = (pnl_usd / info["risk_usd"]) if info["risk_usd"] > 0 else 0.0
            acc = self.connector.get_account_status()
            curr_bal = acc.balance if acc else 0.0

            # Kirim notifikasi Telegram saat posisi selesai (Exit)
            self.telegram.notify_exit(
                session=info["session"],
                direction=info["direction"],
                volume=info["volume"],
                open_price=info["price_open"],
                close_price=exit_price,
                pnl_usd=pnl_usd,
                r_multiple=r_mult,
                reason=reason,
                ticket=ticket,
                balance=curr_bal,
                symbol=info.get("symbol", lcfg.SYMBOL),
            )

            # Catat ke Trade Journal CSV & File Log
            self.journal.record_exit(
                session=info["session"],
                ticket=ticket,
                action=info["direction"],
                volume=info["volume"],
                open_price=info["price_open"],
                close_price=exit_price,
                sl=info["sl"],
                tp=info["tp"],
                net_pnl_usd=pnl_usd,
                r_multiple=r_mult,
                exit_reason=reason,
                slippage_pts=0.0,
                comment=info.get("comment", ""),
            )
            self.logger.info(f"[🎯 POSISI SELESAI] {info['session']} Ticket {ticket} -> Net PnL: ${pnl_usd:+.2f} ({r_mult:+.2f}R) | Alasan: {reason}")

            del self.tracked_positions[ticket]

    # ─────────────────────────────────────────────────────────────
    # OCO (ONE-CANCELS-THE-OTHER) HANDLER (Point #1 Audit)
    # ─────────────────────────────────────────────────────────────
    def _handle_oco_cancellation(self, open_positions: list, open_pendings: list):
        """Jika salah satu order stop terpicu dan aktif, batalkan pending order seberangnya."""
        for pos in open_positions:
            comm = pos.comment
            if "London" in comm:
                # Batalkan semua pending order London yang masih tersisa
                for pend in open_pendings:
                    if "London" in pend.comment:
                        self.logger.info(f"[⚡ OCO TRIGGERED] Posisi London aktif (Ticket {pos.ticket}). Membatalkan Pending Order Ticket {pend.ticket}...")
                        self.connector.cancel_pending_order(pend.ticket)
                        self.trades_today["LONDON"] = True
            elif "NY" in comm:
                # Batalkan semua pending order NY yang masih tersisa
                for pend in open_pendings:
                    if "NY" in pend.comment:
                        self.logger.info(f"[⚡ OCO TRIGGERED] Posisi NY aktif (Ticket {pos.ticket}). Membatalkan Pending Order Ticket {pend.ticket}...")
                        self.connector.cancel_pending_order(pend.ticket)
                        self.trades_today["NY"] = True

    # ─────────────────────────────────────────────────────────────
    # MODUL 1: ASIAN MEAN REVERSION (01:00 - 04:30 UTC)
    # ─────────────────────────────────────────────────────────────
    def _evaluate_asian_mr(self, df_m5: pd.DataFrame, now_utc: datetime, tick: dict, equity: float):
        if not lcfg.ENABLE_ASIAN_MR or self.trades_today["ASIAN"]:
            return

        hm = (now_utc.hour, now_utc.minute)
        sched = self.today_schedule
        if not (sched["ASIAN_START"] <= hm < sched["ASIAN_END"]):
            return

        # Sinyal Asia dievaluasi pada bar M5 yang baru saja selesai
        df_asia = compute_asian_indicators(df_m5)
        eval_row = df_asia.iloc[-2]
        sig = check_asian_entry(eval_row, len(df_asia) - 2)
        if sig is None:
            return

        # Proteksi Spread
        if tick["spread"] > lcfg.MAX_SPREAD_USD:
            return

        risk_usd = equity * lcfg.ASIAN_RISK_PCT
        sl_dist = abs(sig.entry_price - sig.stop_loss)
        if sl_dist <= 0:
            return

        raw_lot = risk_usd / (sl_dist * lcfg.POINT_VALUE)
        lot = max(lcfg.MIN_LOT, min(round(raw_lot / lcfg.LOT_STEP) * lcfg.LOT_STEP, lcfg.MAX_LOT))
        lot = round(lot, 2)

        dir_str = "BUY" if sig.direction == AsianDirection.LONG else "SELL"
        self.logger.info(f"\n[🚀 SINYAL ASIA MR] {dir_str} {lot} Lot XAU/USD | Entry: {sig.entry_price:.2f} | SL: {sig.stop_loss:.2f} | TP: {sig.take_profit:.2f}")

        res = self.connector.open_market_order(
            direction=dir_str,
            volume=lot,
            sl=sig.stop_loss,
            tp=sig.take_profit,
            comment="AsiaMR-FLG"
        )
        self._handle_order_result("ASIAN", res)

    # ─────────────────────────────────────────────────────────────
    # MODUL 2: LONDON PIT ORB (08:15 - 11:30 UTC)
    # ─────────────────────────────────────────────────────────────
    def _evaluate_london_orb(self, df_m5: pd.DataFrame, now_utc: datetime, tick: dict, equity: float, open_pendings: list):
        if not lcfg.ENABLE_LONDON_ORB or self.trades_today["LONDON"]:
            return

        hm = (now_utc.hour, now_utc.minute)
        sched = self.today_schedule

        # 1. Hitung Box Opening Range (08:00 - 08:15)
        if self.london_or_high is None and hm >= sched["LONDON_ENTRY_START"]:
            df_day = df_m5[df_m5["datetime"].dt.date == now_utc.date()]
            or_h, or_m = sched["LONDON_OR_START"]
            lor_bars = df_day[(df_day["datetime"].dt.hour == or_h) & (df_day["datetime"].dt.minute < 15)]
            if len(lor_bars) >= 2:
                self.london_or_high = lor_bars["high"].max()
                self.london_or_low = lor_bars["low"].min()
                self.london_or_range = self.london_or_high - self.london_or_low
                self.logger.info(f"[📦 LONDON OR FORMED] High: {self.london_or_high:.2f} | Low: {self.london_or_low:.2f} | Range: {self.london_or_range:.2f} pts")

        if self.london_or_high is None or self.london_or_range is None or self.london_or_range <= 0:
            return

        # 2. Cek jendela entri (08:15 - 11:30 UTC)
        if not (sched["LONDON_ENTRY_START"] <= hm < sched["LONDON_ENTRY_END"]):
            return

        risk_usd = equity * lcfg.LONDON_RISK_PCT
        risk = self.london_or_range
        raw_lot = risk_usd / (risk * lcfg.POINT_VALUE)
        lot = max(lcfg.MIN_LOT, min(round(raw_lot / lcfg.LOT_STEP) * lcfg.LOT_STEP, lcfg.MAX_LOT))
        lot = round(lot, 2)

        # MODE B: PENDING STOP ORDER OCO (Point #1 Audit)
        if lcfg.BREAKOUT_EXECUTION_MODE == "PENDING_STOP_OCO":
            if not self.pending_orders["LONDON"] and not self.trades_today["LONDON"]:
                self.logger.info(f"\n[📦 MENANAM STOP ORDER LONDON] Memasang Buy Stop & Sell Stop di server MT5...")
                # Buy Stop di or_high
                bs_sl = self.london_or_low
                bs_tp = self.london_or_high + risk * lcfg.LONDON_TARGET_RR
                res_b = self.connector.place_pending_order("BUY_STOP", lot, self.london_or_high, bs_sl, bs_tp, "London-BuyStop")

                # Sell Stop di or_low
                ss_sl = self.london_or_high
                ss_tp = self.london_or_low - risk * lcfg.LONDON_TARGET_RR
                res_s = self.connector.place_pending_order("SELL_STOP", lot, self.london_or_low, ss_sl, ss_tp, "London-SellStop")

                if res_b.success and res_s.success:
                    self.pending_orders["LONDON"] = [res_b.order_id, res_s.order_id]
                    self.logger.info(f"[✓] BUY STOP (Ticket {res_b.order_id}) & SELL STOP (Ticket {res_s.order_id}) AKTIF DI SERVER BROKER!\n")
                else:
                    self._handle_order_result("LONDON", res_b if not res_b.success else res_s)
            return

        # MODE A: FAST-TICK BREAKOUT WITH EXPANSION FILTER & ANTI-CHASING (100% Causal)
        prev_close = df_m5["close"].shift(1)
        tr1 = df_m5["high"] - df_m5["low"]
        tr2 = (df_m5["high"] - prev_close).abs()
        tr3 = (df_m5["low"] - prev_close).abs()
        tr_series = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        # Candle M5 yang sudah tutup sempurna adalah iloc[-2] (karena iloc[-1] adalah bar berjalan)
        prior_tr = tr_series.iloc[-2]
        prior_tr_sma20 = tr_series.iloc[:-1].rolling(20).mean().iloc[-1]

        if pd.isna(prior_tr_sma20) or prior_tr_sma20 <= 0 or prior_tr <= lcfg.LONDON_EXPANSION * prior_tr_sma20:
            return

        current_ask = tick["ask"]
        current_bid = tick["bid"]

        # Long Breakout
        if current_ask > self.london_or_high:
            # Proteksi Anti-Chasing (Point #3 Audit: Jangan mengejar jika harga sudah melompat jauh)
            if current_ask > self.london_or_high + lcfg.MAX_CHASE_USD:
                self.logger.warning(f"[🛑 ANTI-CHASING LONDON] Ask {current_ask:.2f} sudah melompat > ${lcfg.MAX_CHASE_USD:.2f} di atas OR High ({self.london_or_high:.2f}). Order dibatalkan demi keamanan!")
                self.trades_today["LONDON"] = True
                return

            if tick["spread"] > lcfg.MAX_SPREAD_USD:
                return

            sl = self.london_or_low
            tp = self.london_or_high + risk * lcfg.LONDON_TARGET_RR
            self.logger.info(f"\n[⚡ BREAKOUT LONDON LONG] Ask {current_ask:.2f} > LOR High {self.london_or_high:.2f} | Lot: {lot} | SL: {sl:.2f} | TP: {tp:.2f}")
            res = self.connector.open_market_order("BUY", volume=lot, sl=sl, tp=tp, comment="London-ORB-FLG")
            self._handle_order_result("LONDON", res)

        # Short Breakout
        elif current_bid < self.london_or_low:
            # Proteksi Anti-Chasing (Point #3 Audit)
            if current_bid < self.london_or_low - lcfg.MAX_CHASE_USD:
                self.logger.warning(f"[🛑 ANTI-CHASING LONDON] Bid {current_bid:.2f} sudah melompat > ${lcfg.MAX_CHASE_USD:.2f} di bawah OR Low ({self.london_or_low:.2f}). Order dibatalkan demi keamanan!")
                self.trades_today["LONDON"] = True
                return

            if tick["spread"] > lcfg.MAX_SPREAD_USD:
                return

            sl = self.london_or_high
            tp = self.london_or_low - risk * lcfg.LONDON_TARGET_RR
            self.logger.info(f"\n[⚡ BREAKOUT LONDON SHORT] Bid {current_bid:.2f} < LOR Low {self.london_or_low:.2f} | Lot: {lot} | SL: {sl:.2f} | TP: {tp:.2f}")
            res = self.connector.open_market_order("SELL", volume=lot, sl=sl, tp=tp, comment="London-ORB-FLG")
            self._handle_order_result("LONDON", res)

    # ─────────────────────────────────────────────────────────────
    # MODUL 3: NEW YORK ORB (DYNAMIC DST TRACKING)
    # ─────────────────────────────────────────────────────────────
    def _evaluate_ny_orb(self, df_m5: pd.DataFrame, now_utc: datetime, tick: dict, equity: float, open_pendings: list):
        if not lcfg.ENABLE_NY_ORB or self.trades_today["NY"]:
            return

        hm = (now_utc.hour, now_utc.minute)
        sched = self.today_schedule

        # 1. Hitung Box Opening Range New York (09:30 - 09:45 NY Local)
        if self.ny_or_high is None and hm >= sched["NY_ENTRY_START"]:
            df_day = df_m5[df_m5["datetime"].dt.date == now_utc.date()]
            or_h, or_m = sched["NY_OR_START"]
            or_bars = df_day[(df_day["datetime"].dt.hour == or_h) & (df_day["datetime"].dt.minute >= or_m) & (df_day["datetime"].dt.minute < or_m + 15)]
            if len(or_bars) >= 2:
                self.ny_or_high = or_bars["high"].max()
                self.ny_or_low = or_bars["low"].min()
                self.ny_or_range = self.ny_or_high - self.ny_or_low
                self.logger.info(f"[📦 NY OR FORMED ({sched.get('NY_TZ_NAME', 'UTC')})] High: {self.ny_or_high:.2f} | Low: {self.ny_or_low:.2f} | Range: {self.ny_or_range:.2f} pts")

        if self.ny_or_high is None or self.ny_or_range is None or self.ny_or_range <= 0:
            return

        # 2. Cek jendela entri (09:45 - 12:30 NY Local)
        if not (sched["NY_ENTRY_START"] <= hm < sched["NY_ENTRY_END"]):
            return

        risk_usd = equity * lcfg.NY_RISK_PCT
        risk = self.ny_or_range
        raw_lot = risk_usd / (risk * lcfg.POINT_VALUE)
        lot = max(lcfg.MIN_LOT, min(round(raw_lot / lcfg.LOT_STEP) * lcfg.LOT_STEP, lcfg.MAX_LOT))
        lot = round(lot, 2)

        # MODE B: PENDING STOP ORDER OCO (Point #1 Audit)
        if lcfg.BREAKOUT_EXECUTION_MODE == "PENDING_STOP_OCO":
            if not self.pending_orders["NY"] and not self.trades_today["NY"]:
                self.logger.info(f"\n[📦 MENANAM STOP ORDER NY] Memasang Buy Stop & Sell Stop di server MT5...")
                # Buy Stop di or_high
                bs_sl = self.ny_or_low
                bs_tp = self.ny_or_high + risk * lcfg.NY_TARGET_RR
                res_b = self.connector.place_pending_order("BUY_STOP", lot, self.ny_or_high, bs_sl, bs_tp, "NY-BuyStop")

                # Sell Stop di or_low
                ss_sl = self.ny_or_high
                ss_tp = self.ny_or_low - risk * lcfg.NY_TARGET_RR
                res_s = self.connector.place_pending_order("SELL_STOP", lot, self.ny_or_low, ss_sl, ss_tp, "NY-SellStop")

                if res_b.success and res_s.success:
                    self.pending_orders["NY"] = [res_b.order_id, res_s.order_id]
                    self.logger.info(f"[✓] BUY STOP (Ticket {res_b.order_id}) & SELL STOP (Ticket {res_s.order_id}) AKTIF DI SERVER BROKER!\n")
                else:
                    self._handle_order_result("NY", res_b if not res_b.success else res_s)
            return

        # MODE A: FAST-TICK BREAKOUT WITH EXPANSION FILTER & ANTI-CHASING (100% Causal)
        prev_close = df_m5["close"].shift(1)
        tr1 = df_m5["high"] - df_m5["low"]
        tr2 = (df_m5["high"] - prev_close).abs()
        tr3 = (df_m5["low"] - prev_close).abs()
        tr_series = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        # Candle M5 yang sudah tutup sempurna adalah iloc[-2] (karena iloc[-1] adalah bar berjalan)
        prior_tr = tr_series.iloc[-2]
        prior_tr_sma20 = tr_series.iloc[:-1].rolling(20).mean().iloc[-1]

        if pd.isna(prior_tr_sma20) or prior_tr_sma20 <= 0 or prior_tr <= lcfg.NY_EXPANSION * prior_tr_sma20:
            return

        current_ask = tick["ask"]
        current_bid = tick["bid"]

        # Long Breakout
        if current_ask > self.ny_or_high:
            # Proteksi Anti-Chasing (Point #3 Audit)
            if current_ask > self.ny_or_high + lcfg.MAX_CHASE_USD:
                self.logger.warning(f"[🛑 ANTI-CHASING NY] Ask {current_ask:.2f} sudah melompat > ${lcfg.MAX_CHASE_USD:.2f} di atas NY High ({self.ny_or_high:.2f}). Order dibatalkan demi keamanan!")
                self.trades_today["NY"] = True
                return

            if tick["spread"] > lcfg.MAX_SPREAD_USD:
                return

            sl = self.ny_or_low
            tp = self.ny_or_high + risk * lcfg.NY_TARGET_RR
            self.logger.info(f"\n[⚡ BREAKOUT NY LONG] Ask {current_ask:.2f} > NY High {self.ny_or_high:.2f} | Lot: {lot} | SL: {sl:.2f} | TP: {tp:.2f}")
            res = self.connector.open_market_order("BUY", volume=lot, sl=sl, tp=tp, comment="NY-ORB-FLG")
            self._handle_order_result("NY", res)

        # Short Breakout
        elif current_bid < self.ny_or_low:
            # Proteksi Anti-Chasing (Point #3 Audit)
            if current_bid < self.ny_or_low - lcfg.MAX_CHASE_USD:
                self.logger.warning(f"[🛑 ANTI-CHASING NY] Bid {current_bid:.2f} sudah melompat > ${lcfg.MAX_CHASE_USD:.2f} di bawah NY Low ({self.ny_or_low:.2f}). Order dibatalkan demi keamanan!")
                self.trades_today["NY"] = True
                return

            if tick["spread"] > lcfg.MAX_SPREAD_USD:
                return

            sl = self.ny_or_high
            tp = self.ny_or_low - risk * lcfg.NY_TARGET_RR
            self.logger.info(f"\n[⚡ BREAKOUT NY SHORT] Bid {current_bid:.2f} < NY Low {self.ny_or_low:.2f} | Lot: {lot} | SL: {sl:.2f} | TP: {tp:.2f}")
            res = self.connector.open_market_order("SELL", volume=lot, sl=sl, tp=tp, comment="NY-ORB-FLG")
            self._handle_order_result("NY", res)

    # ─────────────────────────────────────────────────────────────
    # REQUOTE & ANTI-SPAM LOCKOUT HANDLER (Point #2 Audit)
    # ─────────────────────────────────────────────────────────────
    def _handle_order_result(self, session: str, res):
        """Kelola hasil pengiriman order dengan proteksi max-retries (Point #2 Audit)."""
        if res.success:
            self.logger.info(f"[✓] ORDER {session} BERHASIL! Ticket: {res.order_id} @ {res.price}\n")
            self.trades_today[session] = True
            self.retry_counts[session] = 0
        else:
            self.retry_counts[session] += 1
            self.logger.error(f"[X] ORDER {session} GAGAL ({self.retry_counts[session]}/{lcfg.MAX_SESSION_RETRIES}): {res.comment}")

            # Jika penolakan karena AutoTrading dimatikan oleh client
            if res.retcode == 10027:
                self.logger.warning("[⚠️ AKSI DIPERLUKAN] Tombol 'Algo Trading' di terminal MT5 belum aktif! Silakan klik tombol 'Algo Trading' pada toolbar MT5 agar menjadi hijau.")

            # Jika mencapai batas maksimal retry, kunci sesi hari ini untuk mencegah API banned
            if self.retry_counts[session] >= lcfg.MAX_SESSION_RETRIES:
                self.logger.warning(f"[🔒 SESI DILOCKOUT] Batas maksimal percobaan ({lcfg.MAX_SESSION_RETRIES}x) tercapai. Sesi {session} dikunci hari ini untuk melindungi akun dari requote spamming.")
                self.trades_today[session] = True
            else:
                self.logger.info(f"[*] Menunggu jeda {lcfg.RETRY_COOLDOWN_SEC} detik sebelum retry berikutnya...\n")
                time.sleep(lcfg.RETRY_COOLDOWN_SEC)

    # ─────────────────────────────────────────────────────────────
    # PENGELOLAAN POSISI AKTIF & SESSION CUTOFFS
    # ─────────────────────────────────────────────────────────────
    def _manage_open_positions(self, positions: list, df_m5: pd.DataFrame, now_utc: datetime):
        """Kelola kondisi keluar khusus (Z-Score Neutral, Session Cutoff)."""
        hm = (now_utc.hour, now_utc.minute)
        sched = self.today_schedule

        for pos in positions:
            ticket = pos.ticket
            profit = pos.profit
            comment = pos.comment

            # 1. Kelola Posisi Asia Mean Reversion
            if "AsiaMR" in comment:
                # A. Hard Cutoff 06:00 UTC
                if hm >= sched["ASIAN_CUTOFF"]:
                    self.logger.info(f"[!] Session Cutoff Asia (06:00 UTC) tercapai. Menutup Ticket {ticket} (PnL: ${profit:+.2f})...")
                    self.connector.close_position(ticket, comment="Cutoff-06:00")
                    continue

                # B. Smart Exit Z-score Mean Reversion
                df_asia = compute_asian_indicators(df_m5)
                latest_z = df_asia["zscore"].iloc[-2]
                is_buy = (pos.type == mt5.ORDER_TYPE_BUY)

                if is_buy and latest_z >= -0.2:
                    self.logger.info(f"[🎯 TP MEAN-REVERSION ASIA] Z-Score netral ({latest_z:.2f} >= -0.2). Menutup Ticket {ticket} (PnL: ${profit:+.2f})...")
                    self.connector.close_position(ticket, comment="TP-Z-Neutral")
                    continue
                elif not is_buy and latest_z <= 0.2:
                    self.logger.info(f"[🎯 TP MEAN-REVERSION ASIA] Z-Score netral ({latest_z:.2f} <= +0.2). Menutup Ticket {ticket} (PnL: ${profit:+.2f})...")
                    self.connector.close_position(ticket, comment="TP-Z-Neutral")
                    continue

            # 2. Kelola Posisi London Pit ORB
            elif "London" in comment:
                if hm >= sched["LONDON_CUTOFF"]:
                    self.logger.info(f"[!] Session Cutoff London tercapai. Menutup Ticket {ticket} (PnL: ${profit:+.2f})...")
                    self.connector.close_position(ticket, comment="Cutoff-London")
                    continue

            # 3. Kelola Posisi New York ORB
            elif "NY" in comment:
                if hm >= sched["NY_CUTOFF"]:
                    self.logger.info(f"[!] Session Cutoff NY tercapai. Menutup Ticket {ticket} (PnL: ${profit:+.2f})...")
                    self.connector.close_position(ticket, comment="Cutoff-NY")
                    continue


if __name__ == "__main__":
    bot = LivePortfolioTrader()
    bot.start()

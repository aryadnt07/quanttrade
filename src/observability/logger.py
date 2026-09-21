"""
Institutional Logging & Audit Journal Engine
============================================
Modul logging profesional untuk sistem live trading:
1. Dual-Logging: Stream ke CMD & TimedRotatingFileHandler (harian) di logs/.
2. QuickEdit Protection: Mematikan QuickEdit Mode di Windows Console agar bot
   tidak pernah beku (freeze) saat kursor mouse tidak sengaja mengklik terminal.
3. Live Trade Journal: Pencatatan otomatis setiap transaksi (Entry & Exit)
   ke berkas CSV bersih (logs/live_trade_journal.csv) untuk audit & analisis.
"""

import os
import sys
import time
import csv
import threading
import logging
from logging.handlers import TimedRotatingFileHandler
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any


def disable_quick_edit_mode() -> bool:
    """Mematikan QuickEdit Mode pada Windows Console via Win32 API."""
    if sys.platform != "win32":
        return False

    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        STD_INPUT_HANDLE = -10
        h_stdin = kernel32.GetStdHandle(STD_INPUT_HANDLE)

        if h_stdin is None or h_stdin == -1:
            return False

        mode = ctypes.c_uint32()
        if not kernel32.GetConsoleMode(h_stdin, ctypes.byref(mode)):
            return False

        ENABLE_QUICK_EDIT_MODE = 0x0040
        ENABLE_EXTENDED_FLAGS  = 0x0080

        new_mode = (mode.value & ~ENABLE_QUICK_EDIT_MODE) | ENABLE_EXTENDED_FLAGS
        success = kernel32.SetConsoleMode(h_stdin, new_mode)
        return bool(success)
    except Exception:
        return False


class UTCFormatter(logging.Formatter):
    """Formatter logging dengan format standar UTC."""
    converter = time.gmtime


_LOGGER_INSTANCE: Optional[logging.Logger] = None
_LOGGER_LOCK = threading.Lock()


def setup_logger(
    name: str = "QuantLive",
    log_dir: Optional[str] = None,
    backup_days: int = 30,
    console_level: str = "INFO",
    file_level: str = "DEBUG"
) -> logging.Logger:
    """Inisialisasi atau ambil instance logger terpadu singleton."""
    global _LOGGER_INSTANCE

    with _LOGGER_LOCK:
        if _LOGGER_INSTANCE is not None:
            return _LOGGER_INSTANCE

        logger = logging.getLogger(name)
        logger.setLevel(logging.DEBUG)
        logger.handlers.clear()
        logger.propagate = False

        if log_dir is None:
            log_dir = os.path.join(os.getcwd(), "logs")

        os.makedirs(log_dir, exist_ok=True)
        log_file_path = os.path.join(log_dir, "live_trading.log")

        # 1. TimedRotatingFileHandler (Rotasi Tengah Malam UTC)
        try:
            file_handler = TimedRotatingFileHandler(
                filename=log_file_path,
                when="midnight",
                interval=1,
                backupCount=backup_days,
                encoding="utf-8",
                utc=True
            )
            file_handler.suffix = "%Y-%m-%d.log"
            file_num_level = getattr(logging, file_level.upper(), logging.DEBUG)
            file_handler.setLevel(file_num_level)
            file_fmt = UTCFormatter(
                fmt="[%(asctime)s UTC] [%(levelname)-7s] [%(name)s] %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S"
            )
            file_handler.setFormatter(file_fmt)
            logger.addHandler(file_handler)
        except Exception as e:
            sys.stderr.write(f"Warning: Gagal inisialisasi file logger: {e}\n")

        # 2. Console Stream Handler
        console_handler = logging.StreamHandler(sys.stdout)
        console_num_level = getattr(logging, console_level.upper(), logging.INFO)
        console_handler.setLevel(console_num_level)
        console_fmt = UTCFormatter(
            fmt="[%(asctime)s UTC] %(message)s",
            datefmt="%H:%M:%S"
        )
        console_handler.setFormatter(console_fmt)
        logger.addHandler(console_handler)

        _LOGGER_INSTANCE = logger
        return logger


def get_logger() -> logging.Logger:
    if _LOGGER_INSTANCE is None:
        return setup_logger()
    return _LOGGER_INSTANCE


JOURNAL_HEADERS = [
    "timestamp_utc",
    "event_type",     # ENTRY atau EXIT
    "session",        # Asia MR, London ORB, New York ORB
    "ticket",         # MT5 Ticket ID
    "action",         # BUY atau SELL
    "volume",         # Lot size
    "open_price",     # Harga pembukaan
    "close_price",    # Harga penutupan (hanya saat EXIT)
    "sl",             # Stop Loss
    "tp",             # Take Profit
    "slippage_pts",   # Slippage dalam points
    "net_pnl_usd",    # Keuntungan/kerugian bersih ($)
    "r_multiple",     # R-Multiple (+2.0R, -1.0R, dll.)
    "exit_reason",    # TP_HIT, SL_HIT, CUTOFF, MANUAL, RECOVERY
    "comment"         # Komentar strategi
]


class TradeJournal:
    """Pencatat transaksi live trading ke berkas CSV terstruktur."""

    def __init__(self, filepath: Optional[str] = None):
        if filepath is None:
            filepath = os.path.join(os.getcwd(), "logs", "live_trade_journal.csv")
        self.filepath = filepath
        self._lock = threading.Lock()
        self._ensure_file_ready()

    def _ensure_file_ready(self):
        with self._lock:
            parent_dir = os.path.dirname(self.filepath)
            if parent_dir:
                os.makedirs(parent_dir, exist_ok=True)

            if not os.path.exists(self.filepath) or os.path.getsize(self.filepath) == 0:
                with open(self.filepath, mode="w", newline="", encoding="utf-8") as f:
                    writer = csv.writer(f)
                    writer.writerow(JOURNAL_HEADERS)

    def record_entry(
        self,
        session: str,
        ticket: int,
        action: str,
        volume: float,
        open_price: float,
        sl: float,
        tp: float,
        slippage_pts: float = 0.0,
        comment: str = "",
        timestamp_utc: Optional[str] = None
    ) -> bool:
        if timestamp_utc is None:
            timestamp_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

        row = [
            timestamp_utc,
            "ENTRY",
            session,
            ticket,
            action,
            f"{volume:.2f}",
            f"{open_price:.3f}",
            "",
            f"{sl:.3f}",
            f"{tp:.3f}",
            f"{slippage_pts:.1f}",
            "",
            "",
            "",
            comment
        ]
        return self._append_row(row)

    def record_exit(
        self,
        session: str,
        ticket: int,
        action: str,
        volume: float,
        open_price: float,
        close_price: float,
        sl: float,
        tp: float,
        net_pnl_usd: float,
        r_multiple: float,
        exit_reason: str,
        slippage_pts: float = 0.0,
        comment: str = "",
        timestamp_utc: Optional[str] = None
    ) -> bool:
        if timestamp_utc is None:
            timestamp_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

        pnl_str = f"{net_pnl_usd:+.2f}"
        r_str = f"{r_multiple:+.2f}R"

        row = [
            timestamp_utc,
            "EXIT",
            session,
            ticket,
            action,
            f"{volume:.2f}",
            f"{open_price:.3f}",
            f"{close_price:.3f}",
            f"{sl:.3f}",
            f"{tp:.3f}",
            f"{slippage_pts:.1f}",
            pnl_str,
            r_str,
            exit_reason,
            comment
        ]
        return self._append_row(row)

    def _append_row(self, row: list) -> bool:
        with self._lock:
            try:
                with open(self.filepath, mode="a", newline="", encoding="utf-8") as f:
                    writer = csv.writer(f)
                    writer.writerow(row)
                return True
            except Exception as e:
                sys.stderr.write(f"Gagal mencatat trade journal: {e}\n")
                return False

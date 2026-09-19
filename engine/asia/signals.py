"""
Asian Mean Reversion — Signal Generator
=========================================
Logika sinyal entry/exit dengan filter volatilitas dan konfirmasi candle.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional

import pandas as pd

from configs import asia_config as cfg


# ─────────────────────────────────────────────
#  ENUMS & DATA CLASSES
# ─────────────────────────────────────────────

class Direction(Enum):
    LONG = "LONG"
    SHORT = "SHORT"


class ExitReason(Enum):
    TAKE_PROFIT = "TP_Z_NEUTRAL"        # Z kembali ke area ekuilibrium
    STOP_LOSS = "SL_ATR"                # Harga menyentuh SL (1.5 × ATR)
    HARD_CUT = "HARD_CUT_Z"            # |Z| > 3.2
    TIME_STOP = "TIME_STOP_60M"         # Durasi > 60 menit
    SESSION_CUTOFF = "SESSION_CUTOFF"   # >= 06:00 UTC


@dataclass
class Signal:
    """Representasi satu sinyal trading."""
    bar_index: int
    datetime: pd.Timestamp
    direction: Direction
    entry_price: float
    stop_loss: float
    take_profit: float
    zscore: float
    rsi: float
    atr: float
    lot_size: float = 0.1


@dataclass
class TradeResult:
    """Hasil akhir satu trade (setelah exit)."""
    entry_signal: Signal
    exit_index: int
    exit_datetime: pd.Timestamp
    exit_price: float
    exit_reason: ExitReason
    pnl_points: float           # Profit/loss dalam poin harga
    pnl_usd: float              # Profit/loss dalam USD
    duration_minutes: float     # Durasi trade dalam menit
    lot_size: float = 0.1       # Ukuran lot yang dieksekusi
    mfe_usd: float = 0.0        # Maximum Favorable Excursion (Highest floating profit)
    mae_usd: float = 0.0        # Maximum Adverse Excursion (Lowest floating profit)


# ─────────────────────────────────────────────
#  CANDLE CONFIRMATION HELPERS
# ─────────────────────────────────────────────

def _is_bearish_candle(row: pd.Series) -> bool:
    """Candle bearish: close < open."""
    return row["close"] < row["open"]


def _is_bullish_candle(row: pd.Series) -> bool:
    """Candle bullish: close > open."""
    return row["close"] > row["open"]


# ─────────────────────────────────────────────
#  SESSION & VOLATILITY FILTERS
# ─────────────────────────────────────────────

def _is_in_entry_window(dt: pd.Timestamp) -> bool:
    """Cek apakah waktu berada dalam jendela entri (misal: 01:00-04:30 UTC)."""
    hour = dt.hour
    start_h, start_m = map(int, cfg.SESSION_ENTRY_START.split(":"))
    end_h, end_m = map(int, cfg.SESSION_ENTRY_END.split(":"))
    start_minutes = start_h * 60 + start_m
    end_minutes = end_h * 60 + end_m
    current_minutes = hour * 60 + dt.minute
    return start_minutes <= current_minutes < end_minutes


def _passes_volatility_filter(atr: float, atr_sma: float) -> bool:
    """
    Gerbang volatilitas:
    1. ATR >= min threshold ($0.80)
    2. ATR <= 1.6 × SMA(ATR, 50)
    """
    if pd.isna(atr) or pd.isna(atr_sma):
        return False

    # Gerbang bawah
    if atr < cfg.ATR_MIN_THRESHOLD:
        return False

    # Gerbang atas
    max_atr = cfg.ATR_ANOMALY_MULTIPLIER * atr_sma
    if atr > max_atr:
        return False

    return True


def _calculate_lot_size(entry_price: float, sl: float) -> float:
    """Hitung lot dinamis berbasis fixed dollar risk jika diaktifkan."""
    if not getattr(cfg, "USE_DYNAMIC_LOT", False):
        return getattr(cfg, "LOT_SIZE", 0.1)

    sl_dist = abs(entry_price - sl)
    if sl_dist <= 0:
        return getattr(cfg, "LOT_SIZE", 0.1)

    point_val = getattr(cfg, "POINT_VALUE", 100.0)
    risk_usd = getattr(cfg, "FIXED_RISK_USD", 80.0)
    raw_lot = risk_usd / (sl_dist * point_val)

    step = getattr(cfg, "LOT_STEP", 0.01)
    lot = round(round(raw_lot / step) * step, 2)
    min_lot = getattr(cfg, "MIN_LOT", 0.01)
    max_lot = getattr(cfg, "MAX_LOT", 2.0)
    return max(min_lot, min(lot, max_lot))


# ─────────────────────────────────────────────
#  SIGNAL GENERATION (ENTRY)
# ─────────────────────────────────────────────

def check_entry_signal(row: pd.Series, idx: int) -> Optional[Signal]:
    """
    Evaluasi bar saat ini untuk sinyal entry (LONG atau SHORT).
    Kembalikan objek Signal jika valid, atau None jika tidak ada sinyal.
    """
    if not _is_in_entry_window(row["datetime"]):
        return None

    atr = row["atr"]
    atr_sma = row["atr_sma"]
    if not _passes_volatility_filter(atr, atr_sma):
        return None

    # Cek data valid
    zscore = row.get("zscore", None)
    rsi = row.get("rsi", None)
    close = row.get("close", None)

    if pd.isna(zscore) or pd.isna(rsi) or pd.isna(atr) or pd.isna(close):
        return None

    # Filter RSI jika diaktifkan di config
    rsi_short_valid = (not getattr(cfg, "USE_RSI_FILTER", True)) or (rsi >= cfg.RSI_OVERBOUGHT)
    rsi_long_valid = (not getattr(cfg, "USE_RSI_FILTER", True)) or (rsi <= cfg.RSI_OVERSOLD)

    # Filter HTF Trend jika diaktifkan di config
    short_htf_ok = True
    long_htf_ok = True
    if getattr(cfg, "USE_HTF_TREND_FILTER", False):
        htf_ema = row.get("htf_ema", None)
        if pd.notna(htf_ema):
            mode = getattr(cfg, "HTF_FILTER_MODE", "SYMMETRIC")
            if mode == "SYMMETRIC":
                short_htf_ok = close < htf_ema
                long_htf_ok = close > htf_ema
            elif mode == "ASYMMETRIC_LONG_ONLY":
                short_htf_ok = True
                long_htf_ok = close > htf_ema

    # ── KONDISI SHORT ──
    if zscore >= cfg.Z_ENTRY_THRESHOLD and rsi_short_valid and short_htf_ok:
        if not cfg.REQUIRE_OPPOSING_CLOSE or _is_bearish_candle(row):
            entry_price = close
            sl = entry_price + (atr * cfg.ATR_SL_MULTIPLIER)
            tp = row["anchor"]  # Target: kembali ke mean (Z ≈ 0)
            lot = _calculate_lot_size(entry_price, sl)
            return Signal(
                bar_index=idx,
                datetime=row["datetime"],
                direction=Direction.SHORT,
                entry_price=entry_price,
                stop_loss=sl,
                take_profit=tp,
                zscore=zscore,
                rsi=rsi,
                atr=atr,
                lot_size=lot,
            )

    # ── KONDISI LONG ──
    if zscore <= -cfg.Z_ENTRY_THRESHOLD and rsi_long_valid and long_htf_ok:
        if not cfg.REQUIRE_OPPOSING_CLOSE or _is_bullish_candle(row):
            entry_price = close
            sl = entry_price - (atr * cfg.ATR_SL_MULTIPLIER)
            tp = row["anchor"]  # Target: kembali ke mean (Z ≈ 0)
            lot = _calculate_lot_size(entry_price, sl)
            return Signal(
                bar_index=idx,
                datetime=row["datetime"],
                direction=Direction.LONG,
                entry_price=entry_price,
                stop_loss=sl,
                take_profit=tp,
                zscore=zscore,
                rsi=rsi,
                atr=atr,
                lot_size=lot,
            )

    return None


# ─────────────────────────────────────────────
#  EXIT LOGIC
# ─────────────────────────────────────────────

def check_exit_conditions(
    row: pd.Series,
    signal: Signal,
) -> Optional[ExitReason]:
    """
    Evaluasi apakah posisi terbuka harus ditutup pada bar ini.
    
    Returns ExitReason jika harus exit, None jika hold.
    """
    dt = row["datetime"]
    close = row["close"]
    high = row["high"]
    low = row["low"]
    zscore = row.get("zscore", 0)

    # Session Cutoff (Market Tutup / Hard Kill Switch)
    time_str = dt.strftime("%H:%M")
    if time_str >= cfg.SESSION_HARD_CUTOFF:
        return ExitReason.SESSION_CUTOFF

    # Jika posisi dibuka di hari berbeda (cross-day), tutup di awal sesi baru
    if dt.date() != signal.datetime.date():
        return ExitReason.SESSION_CUTOFF

    # Jika ini bar terakhir sesi (5 menit sebelum hard cutoff), tutup
    end_h, end_m = map(int, cfg.SESSION_HARD_CUTOFF.split(":"))
    end_minutes = end_h * 60 + end_m
    current_minutes = dt.hour * 60 + dt.minute
    if current_minutes >= end_minutes - 5:
        return ExitReason.SESSION_CUTOFF

    # TIME STOP (60 menit)
    duration = (dt - signal.datetime).total_seconds() / 60.0
    if duration >= cfg.MAX_TRADE_DURATION_MIN:
        return ExitReason.TIME_STOP

    # HARD CUT (|Z| > 3.2)
    if signal.direction == Direction.SHORT and zscore >= cfg.Z_HARD_CUT:
        return ExitReason.HARD_CUT
    if signal.direction == Direction.LONG and zscore <= -cfg.Z_HARD_CUT:
        return ExitReason.HARD_CUT

    # STOP LOSS
    if signal.direction == Direction.SHORT and high >= signal.stop_loss:
        return ExitReason.STOP_LOSS
    if signal.direction == Direction.LONG and low <= signal.stop_loss:
        return ExitReason.STOP_LOSS

    # TAKE PROFIT
    if -cfg.Z_EXIT_THRESHOLD <= zscore <= cfg.Z_EXIT_THRESHOLD:
        return ExitReason.TAKE_PROFIT

    return None


def get_exit_price(
    row: pd.Series,
    signal: Signal,
    reason: ExitReason,
) -> float:
    """
    Tentukan harga exit berdasarkan alasan exit.
    """
    if reason == ExitReason.STOP_LOSS:
        return signal.stop_loss

    if reason == ExitReason.TAKE_PROFIT:
        return signal.take_profit

    return row["close"]

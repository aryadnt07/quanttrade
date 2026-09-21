"""
Market Data CSV Loader & Preprocessor
=====================================
Load, validasi, dan preprocessing data CSV historis pasar XAU/USD (M1/M5/M15/H1/H4).
Decoupled dari konfigurasi strategi khusus (Fix V4).
"""

import os
from pathlib import Path
import pandas as pd


REQUIRED_OHLC = {"open", "high", "low", "close"}


def load_csv(filepath: str) -> pd.DataFrame:
    """
    Load data CSV dan lakukan validasi + preprocessing standar.
    
    Format CSV yang didukung:
        1. datetime, open, high, low, close [, volume]
        2. timestamp (epoch ms/s), open, high, low, close [, volume]
        3. date, time, open, high, low, close [, volume]
    
    Returns:
        pd.DataFrame terurut kronologis dengan kolom:
        datetime (Timestamp UTC), open, high, low, close, volume (opsional).
    """
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"Data file tidak ditemukan: {filepath}")

    df = pd.read_csv(filepath)

    # Normalisasi nama kolom (lowercase, strip whitespace)
    df.columns = df.columns.str.strip().str.lower()

    # Validasi kolom OHLC wajib
    missing_ohlc = REQUIRED_OHLC - set(df.columns)
    if missing_ohlc:
        raise ValueError(
            f"Kolom OHLC wajib tidak ditemukan: {missing_ohlc}. "
            f"Kolom yang tersedia: {list(df.columns)}"
        )

    # 1. Parse datetime
    if "datetime" in df.columns:
        df["datetime"] = pd.to_datetime(df["datetime"], utc=True)
    elif "timestamp" in df.columns:
        ts = pd.to_numeric(df["timestamp"], errors="coerce")
        if ts.median() > 1e12:
            df["datetime"] = pd.to_datetime(ts, unit="ms", utc=True)
        else:
            df["datetime"] = pd.to_datetime(ts, unit="s", utc=True)
        df.drop(columns=["timestamp"], inplace=True, errors="ignore")
    elif "date" in df.columns and "time" in df.columns:
        df["datetime"] = pd.to_datetime(df["date"] + " " + df["time"], utc=True)
        df.drop(columns=["date", "time"], inplace=True, errors="ignore")
    else:
        raise ValueError(
            "Tidak ditemukan kolom waktu. "
            "CSV harus memiliki kolom 'datetime', 'timestamp', atau 'date'+'time'. "
            f"Kolom yang tersedia: {list(df.columns)}"
        )

    # 2. Pastikan tipe numerik
    for col in ["open", "high", "low", "close"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    # 3. Volume handling
    if "volume" in df.columns:
        df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0)
    elif "tick_volume" in df.columns:
        df["volume"] = pd.to_numeric(df["tick_volume"], errors="coerce").fillna(0)
        df.drop(columns=["tick_volume"], inplace=True, errors="ignore")

    # 4. Buang baris dengan NaN pada kolom OHLC
    df.dropna(subset=["open", "high", "low", "close"], inplace=True)

    # 5. Buang bar "frozen" (OHLC semua sama = pasar tutup)
    frozen_mask = (
        (df["open"] == df["high"]) &
        (df["high"] == df["low"]) &
        (df["low"] == df["close"])
    )
    frozen_count = frozen_mask.sum()
    if frozen_count > 0:
        print(f"      [!] Menghapus {frozen_count} bar frozen (pasar tutup)")
        df = df[~frozen_mask].copy()

    # 6. Urutkan berdasarkan waktu
    df.sort_values("datetime", inplace=True)
    df.reset_index(drop=True, inplace=True)

    return df


def filter_session(df: pd.DataFrame, start_time: str = "00:00", end_time: str = "06:00") -> pd.DataFrame:
    """Filter bar dalam rentang jam tertentu (UTC)."""
    start_h, start_m = map(int, start_time.split(":"))
    end_h, end_m = map(int, end_time.split(":"))

    start_minutes = start_h * 60 + start_m
    end_minutes = end_h * 60 + end_m

    time_minutes = df["datetime"].dt.hour * 60 + df["datetime"].dt.minute
    mask = (time_minutes >= start_minutes) & (time_minutes < end_minutes)
    return df[mask].copy()


def get_default_data_path(data_dir: str = "data", filename: str = "xauusd-m5-bid-2021-09-08-2026-09-08.csv") -> str:
    """Return path file data default."""
    return str(Path(data_dir) / filename)

"""
Asian Mean Reversion — Data Loader
====================================
Load, validasi, dan preprocessing data CSV historis XAU/USD M5.
Mendukung format:
  - datetime string (ISO 8601)
  - timestamp epoch milliseconds
"""

import os
from pathlib import Path

import numpy as np
import pandas as pd

import configs.asia_config as cfg


REQUIRED_OHLC = {"open", "high", "low", "close"}


def load_csv(filepath: str) -> pd.DataFrame:
    """
    Load data CSV dan lakukan validasi + preprocessing.
    
    Format CSV yang diterima:
        1. datetime, open, high, low, close [, volume]
        2. timestamp (ms epoch), open, high, low, close [, volume]
    
    Returns
    -------
    pd.DataFrame terurut berdasarkan datetime, dengan kolom:
        datetime (Timestamp, UTC), open, high, low, close, volume (opsional)
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

    # ── Parse datetime ──
    if "datetime" in df.columns:
        # Format 1: kolom datetime string
        df["datetime"] = pd.to_datetime(df["datetime"], utc=True)
    elif "timestamp" in df.columns:
        # Format 2: kolom timestamp epoch (milliseconds)
        ts = pd.to_numeric(df["timestamp"], errors="coerce")
        # Deteksi otomatis: jika nilai > 1e12, asumsi milliseconds
        if ts.median() > 1e12:
            df["datetime"] = pd.to_datetime(ts, unit="ms", utc=True)
        else:
            df["datetime"] = pd.to_datetime(ts, unit="s", utc=True)
        df.drop(columns=["timestamp"], inplace=True, errors="ignore")
    elif "date" in df.columns and "time" in df.columns:
        # Format 3: kolom date + time terpisah
        df["datetime"] = pd.to_datetime(df["date"] + " " + df["time"], utc=True)
        df.drop(columns=["date", "time"], inplace=True, errors="ignore")
    else:
        raise ValueError(
            "Tidak ditemukan kolom waktu. "
            "CSV harus memiliki kolom 'datetime', 'timestamp', atau 'date'+'time'. "
            f"Kolom yang tersedia: {list(df.columns)}"
        )

    # Pastikan tipe numerik
    for col in ["open", "high", "low", "close"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    # Volume (opsional)
    if "volume" in df.columns:
        df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0)
    elif "tick_volume" in df.columns:
        df["volume"] = pd.to_numeric(df["tick_volume"], errors="coerce").fillna(0)
        df.drop(columns=["tick_volume"], inplace=True, errors="ignore")

    # Buang baris dengan NaN pada kolom OHLC
    df.dropna(subset=["open", "high", "low", "close"], inplace=True)

    # Buang bar "frozen" (OHLC semua sama = pasar tutup)
    frozen_mask = (
        (df["open"] == df["high"]) &
        (df["high"] == df["low"]) &
        (df["low"] == df["close"])
    )
    frozen_count = frozen_mask.sum()
    if frozen_count > 0:
        print(f"      [!] Menghapus {frozen_count} bar frozen (pasar tutup)")
        df = df[~frozen_mask].copy()

    # Urutkan berdasarkan waktu
    df.sort_values("datetime", inplace=True)
    df.reset_index(drop=True, inplace=True)

    return df


def filter_asian_session(df: pd.DataFrame) -> pd.DataFrame:
    """
    Filter hanya bar yang berada dalam sesi Asia (00:00-06:00 UTC).
    
    CATATAN: Fungsi ini TIDAK dipakai di backtester karena backtester
    perlu semua data untuk menghitung indikator (rolling window).
    Gunakan ini hanya untuk analisis/visualisasi.
    """
    start_h, start_m = map(int, cfg.SESSION_START_UTC.split(":"))
    end_h, end_m = map(int, cfg.SESSION_END_UTC.split(":"))

    start_minutes = start_h * 60 + start_m
    end_minutes = end_h * 60 + end_m

    time_minutes = df["datetime"].dt.hour * 60 + df["datetime"].dt.minute

    mask = (time_minutes >= start_minutes) & (time_minutes < end_minutes)
    return df[mask].copy()


def get_default_data_path() -> str:
    """Return path default untuk sample data."""
    return str(Path(cfg.DATA_DIR) / cfg.SAMPLE_DATA_FILE)

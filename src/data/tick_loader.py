"""
High-Performance Tick Data Loader & Preprocessor
================================================
Memuat dataset tick XAU/USD (jutaan baris) ke dalam struktur NumPy array
berkinerja tinggi untuk simulasi tick-replay beresolusi milidetik.
"""

import os
from dataclasses import dataclass
from datetime import date
from typing import Optional, Dict, Tuple, List
import pandas as pd
import numpy as np


@dataclass
class TickDaySlice:
    """Slice data tick untuk satu hari kalender."""
    date: date
    start_idx: int
    end_idx: int
    count: int


@dataclass
class TickDataset:
    """Dataset tick berkinerja tinggi berbasis NumPy 64-bit."""
    timestamps_ms: np.ndarray          # int64 epoch ms
    datetimes: pd.DatetimeIndex        # UTC DatetimeIndex
    asks: np.ndarray                   # float64
    bids: np.ndarray                   # float64
    spreads: np.ndarray                # float64 (asks - bids)
    day_slices: Dict[date, Tuple[int, int]]  # date -> (start_idx, end_idx)
    unique_dates: List[date]

    @property
    def total_ticks(self) -> int:
        return len(self.timestamps_ms)

    def __len__(self) -> int:
        return len(self.timestamps_ms)

    @property
    def start_dt(self) -> pd.Timestamp:
        return self.datetimes[0] if len(self.datetimes) > 0 else pd.NaT

    @property
    def end_dt(self) -> pd.Timestamp:
        return self.datetimes[-1] if len(self.datetimes) > 0 else pd.NaT


def load_tick_csv(filepath: str, verbose: bool = True) -> TickDataset:
    """
    Load data tick CSV dan lakukan parsing cepat ke dalam struktur NumPy.
    Format kolom yang didukung:
        timestamp (epoch ms), askPrice, bidPrice
        (atau ask, bid, time/datetime)
    """
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"File data tick tidak ditemukan: {filepath}")

    if verbose:
        print(f"      [TickLoader] Membaca file tick: {filepath}...")

    # Baca CSV
    df = pd.read_csv(filepath)
    df.columns = df.columns.str.strip().str.lower()

    # Identifikasi kolom timestamp
    if "timestamp" in df.columns:
        ts_raw = pd.to_numeric(df["timestamp"], errors="coerce").values.astype(np.int64)
    elif "time" in df.columns:
        ts_raw = pd.to_numeric(df["time"], errors="coerce").values.astype(np.int64)
    else:
        raise ValueError(f"Kolom timestamp tidak ditemukan pada file tick. Kolom: {list(df.columns)}")

    # Deteksi detik vs milidetik
    sample_val = ts_raw[0] if len(ts_raw) > 0 else 0
    if sample_val < 1e11:  # Jika satuan detik, ubah ke ms
        ts_ms = ts_raw * 1000
    else:
        ts_ms = ts_raw

    # Identifikasi kolom ask dan bid
    ask_col = "askprice" if "askprice" in df.columns else ("ask" if "ask" in df.columns else None)
    bid_col = "bidprice" if "bidprice" in df.columns else ("bid" if "bid" in df.columns else None)

    if not ask_col or not bid_col:
        raise ValueError(f"Kolom ask/bid tidak ditemukan. Kolom yang ada: {list(df.columns)}")

    asks = df[ask_col].values.astype(np.float64)
    bids = df[bid_col].values.astype(np.float64)
    spreads = asks - bids

    # Konversi ke DatetimeIndex UTC
    datetimes = pd.to_datetime(ts_ms, unit="ms", utc=True)

    # Pre-index hari kalender (O(1) slicing harian)
    date_series = datetimes.date
    unique_dates_arr, start_indices = np.unique(date_series, return_index=True)
    unique_dates = list(unique_dates_arr)

    day_slices: Dict[date, Tuple[int, int]] = {}
    n_days = len(unique_dates)
    total_len = len(ts_ms)

    for i in range(n_days):
        cur_d = unique_dates[i]
        s_idx = int(start_indices[i])
        e_idx = int(start_indices[i + 1]) if (i + 1 < n_days) else total_len
        day_slices[cur_d] = (s_idx, e_idx)

    if verbose:
        print(f"      [TickLoader] Berhasil memuat {total_len:,} ticks dari {unique_dates[0]} hingga {unique_dates[-1]} ({len(unique_dates)} hari trading)")

    return TickDataset(
        timestamps_ms=ts_ms,
        datetimes=datetimes,
        asks=asks,
        bids=bids,
        spreads=spreads,
        day_slices=day_slices,
        unique_dates=unique_dates,
    )

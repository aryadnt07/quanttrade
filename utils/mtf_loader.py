"""
Multi-Timeframe Data Loader & Causal Alignment Pipeline
======================================================
Modul untuk memuat dan menyelaraskan data multi-timeframe (M5, M15, H1, H4)
dengan jaminan mutlak ZERO LOOK-AHEAD BIAS (Causal Integrity).

Setiap bar Higher Timeframe (HTF) yang dimulai pada waktu T dengan durasi Delta
baru dianggap selesai pada T + Delta. Oleh karena itu, bar M5 pada waktu t
hanya dapat membaca bar HTF yang memiliki (T + Delta) <= t.
"""

import os
from pathlib import Path
from typing import Optional, Dict, Tuple
import numpy as np
import pandas as pd

from utils.data_loader import load_csv


def resample_ohlcv(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    """
    Resample data M5 ke timeframe lebih tinggi (M15, 1h, 4h) secara standar OHLCV.
    """
    df_sorted = df.sort_values("datetime").set_index("datetime")
    agg_dict = {
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last"
    }
    if "volume" in df.columns:
        agg_dict["volume"] = "sum"

    resampled = df_sorted.resample(rule, closed="left", label="left").agg(agg_dict).dropna(subset=["open", "close"]).reset_index()
    return resampled


def compute_htf_indicators(df_htf: pd.DataFrame, tf_name: str) -> pd.DataFrame:
    """
    Hitung indikator standar pada timeframe HTF asli (EMA 50, EMA 200, ATR 14, RSI 14).
    """
    df = df_htf.copy().sort_values("datetime").reset_index(drop=True)
    close = df["close"]
    high = df["high"]
    low = df["low"]
    prev_close = close.shift(1)

    # 1. EMA 50 & 200
    df[f"{tf_name}_ema50"] = close.ewm(span=50, adjust=False).mean()
    df[f"{tf_name}_ema200"] = close.ewm(span=200, adjust=False).mean()

    # 2. ATR 14
    tr = np.maximum(high - low, np.maximum((high - prev_close).abs(), (low - prev_close).abs()))
    df[f"{tf_name}_atr14"] = tr.ewm(alpha=1.0 / 14, adjust=False).mean()

    # 3. RSI 14
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1.0 / 14, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / 14, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    df[f"{tf_name}_rsi14"] = 100.0 - (100.0 / (1.0 + rs))

    return df


def align_htf_to_ltf(
    df_ltf: pd.DataFrame,
    df_htf: pd.DataFrame,
    duration: pd.Timedelta,
    feature_cols: list
) -> pd.DataFrame:
    """
    Gabungkan fitur HTF ke LTF (M5) secara kausal (Zero Look-Ahead Bias).
    
    Bar HTF pada waktu T baru selesai pada T + duration.
    Jadi bar LTF pada waktu t hanya boleh mengakses data HTF jika T + duration <= t.
    """
    df_htf_causal = df_htf.copy()
    avail_col = "_htf_available_dt"
    
    # Pastikan tipe datetime sama persis (misal datetime64[ms, UTC])
    df_htf_causal[avail_col] = (df_htf_causal["datetime"] + duration).astype(df_ltf["datetime"].dtype)
    
    cols_to_merge = [avail_col] + feature_cols
    df_htf_subset = df_htf_causal[cols_to_merge].sort_values(avail_col)

    merged = pd.merge_asof(
        df_ltf.sort_values("datetime"),
        df_htf_subset,
        left_on="datetime",
        right_on=avail_col,
        direction="backward"
    )
    merged.drop(columns=[avail_col], inplace=True, errors="ignore")
    return merged


def load_mtf_dataset(
    m5_path: str,
    h1_path: Optional[str] = None,
    h4_path: Optional[str] = None,
    m15_path: Optional[str] = None
) -> Tuple[pd.DataFrame, Dict[str, pd.DataFrame]]:
    """
    Memuat dataset M5 dan memperkayanya dengan indikator HTF (H1, H4, M15) secara kausal.
    
    Jika file HTF tidak ditemukan di disk, sistem akan otomatis melakukan resample
    dari data M5 secara on-the-fly.
    
    Returns
    -------
    df_m5_enriched : pd.DataFrame
        DataFrame M5 dengan kolom tambahan seperti h1_ema50, h1_ema200, h4_ema200, dll.
    htf_dfs : Dict[str, pd.DataFrame]
        Dictionary berisi DataFrame asli masing-masing timeframe ('M15', 'H1', 'H4').
    """
    print(f"      [*] Loading base M5 data: {m5_path}")
    df_m5 = load_csv(m5_path)

    htf_dfs = {}

    # 1. H1 Processing
    if h1_path and os.path.exists(h1_path):
        print(f"      [*] Loading native H1 data: {h1_path}")
        df_h1 = load_csv(h1_path)
    else:
        print("      [*] H1 file tidak ada, melakukan resample on-the-fly dari M5...")
        df_h1 = resample_ohlcv(df_m5, "1h")
    
    df_h1 = compute_htf_indicators(df_h1, "h1")
    htf_dfs["H1"] = df_h1

    # 2. H4 Processing
    if h4_path and os.path.exists(h4_path):
        print(f"      [*] Loading native H4 data: {h4_path}")
        df_h4 = load_csv(h4_path)
    else:
        print("      [*] H4 file tidak ada, melakukan resample on-the-fly dari M5...")
        df_h4 = resample_ohlcv(df_m5, "4h")
    
    df_h4 = compute_htf_indicators(df_h4, "h4")
    htf_dfs["H4"] = df_h4

    # 3. M15 Processing (opsional)
    if m15_path and os.path.exists(m15_path):
        print(f"      [*] Loading native M15 data: {m15_path}")
        df_m15 = load_csv(m15_path)
    else:
        df_m15 = resample_ohlcv(df_m5, "15min")
    
    df_m15 = compute_htf_indicators(df_m15, "m15")
    htf_dfs["M15"] = df_m15

    # 4. Causal Alignment to M5
    print("      [*] Menyelaraskan indikator HTF ke M5 secara kausal (Zero Look-Ahead)...")
    h1_cols = ["h1_ema50", "h1_ema200", "h1_atr14", "h1_rsi14"]
    df_m5 = align_htf_to_ltf(df_m5, df_h1, pd.Timedelta(hours=1), h1_cols)

    h4_cols = ["h4_ema50", "h4_ema200", "h4_atr14", "h4_rsi14"]
    df_m5 = align_htf_to_ltf(df_m5, df_h4, pd.Timedelta(hours=4), h4_cols)

    return df_m5, htf_dfs

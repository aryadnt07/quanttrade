"""
New York Opening Range Breakout (NY ORB) — Strategy & Signal Generation
========================================================================
Logika kuantitatif New York ORB:
- Pembentukan Opening Range: 13:30 - 13:45 UTC
- Jendela Eksekusi: 13:45 - 16:30 UTC
- Filter Ekspansi: True Range (TR) candle sebelumnya > 1.5 x SMA(20) TR (100% Kausal)
- Stop Loss: or_range penuh (batas seberang)
- Take Profit: 2.0R (entry +/- 2.0 * or_range)
- Entry Level: or_high (Long) atau or_low (Short)
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional
import numpy as np
import pandas as pd

from configs import ny_config as cfg


class Direction(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


@dataclass
class NYSignal:
    """Representasi sinyal entri New York ORB."""
    datetime: pd.Timestamp
    direction: Direction
    entry_price: float
    stop_loss: float
    take_profit: float
    initial_risk: float
    or_high: float
    or_low: float
    or_range: float
    lot_size: float = 0.0


def compute_ny_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Hitung True Range (TR), SMA20 TR, ATR14, dan identifikasi Opening Range M15 (13:30 - 13:45 UTC).
    """
    df = df.copy()
    if not isinstance(df["datetime"].dtype, pd.DatetimeTZDtype):
        df["datetime"] = pd.to_datetime(df["datetime"], utc=True)

    df = df.sort_values("datetime").reset_index(drop=True)

    high = df["high"]
    low = df["low"]
    close = df["close"]
    prev_close = close.shift(1)

    # 1. True Range & SMA20 TR
    tr = np.maximum(high - low, np.maximum((high - prev_close).abs(), (low - prev_close).abs()))
    df["tr"] = tr
    df["tr_past"] = df["tr"].shift(1)
    df["tr_sma20"] = df["tr"].rolling(cfg.EXPANSION_SMA_PERIOD).mean().shift(1)
    df["atr14"] = df["tr"].ewm(alpha=1.0 / 14, adjust=False).mean()

    # 2. Extract Opening Range M15 (13:30 - 13:45 UTC) per date
    df["date"] = df["datetime"].dt.date
    df["hour"] = df["datetime"].dt.hour
    df["minute"] = df["datetime"].dt.minute
    df["time_tuple"] = list(zip(df["hour"], df["minute"]))

    # 13:30 <= time < 13:45
    or_mask = (df["hour"] == 13) & (df["minute"] >= 30) & (df["minute"] < 45)
    or_bars = df[or_mask]

    or_summary = or_bars.groupby("date").agg(
        or_high=("high", "max"),
        or_low=("low", "min"),
        bar_count=("close", "count")
    ).reset_index()

    or_summary["or_range"] = or_summary["or_high"] - or_summary["or_low"]
    # Filter hari dengan minimal bar yang valid
    valid_or = or_summary[(or_summary["bar_count"] >= cfg.MIN_ORB_BARS) & (or_summary["or_range"] > 0)]

    df = df.merge(valid_or[["date", "or_high", "or_low", "or_range"]], on="date", how="left")
    return df


class NYStrategy:
    """Evaluator aturan kuantitatif New York ORB."""

    def __init__(self):
        pass

    def evaluate_bar(self, row: pd.Series) -> Optional[NYSignal]:
        """
        Evaluasi satu bar M5 untuk mencari peluang entri penembusan.
        """
        h_time = (row["hour"], row["minute"])
        # Jendela evaluasi: (13, 45) <= h_time < (16, 30)
        if h_time < (13, 45) or h_time >= (16, 30):
            return None

        or_h = row["or_high"]
        or_l = row["or_low"]
        or_rng = row["or_range"]

        if pd.isna(or_h) or pd.isna(or_l) or pd.isna(or_rng) or or_rng <= 0:
            return None

        # Filter Ekspansi (Kausal 100%: Menggunakan True Range bar sebelumnya yang sudah tutup)
        if cfg.USE_EXPANSION_FILTER:
            tr = row["tr_past"]
            tr_sma = row["tr_sma20"]
            if pd.isna(tr_sma) or tr_sma <= 0:
                return None
            if tr <= cfg.EXPANSION_MULT * tr_sma:
                return None

        # Filter HTF Trend Confluence
        htf_col = getattr(cfg, "HTF_COL", "h1_ema50")
        htf_ema = row.get(htf_col, row.get("h1_ema50", row.get("htf_ema", np.nan)))
        htf_filter_active = getattr(cfg, "USE_HTF_TREND_FILTER", False) and pd.notna(htf_ema)

        # Sinyal Long
        if row["high"] > or_h:
            if htf_filter_active and row["close"] < htf_ema:
                return None
            entry = or_h
            risk = or_rng
            sl = entry - risk
            tp = entry + risk * cfg.TARGET_RR
            return NYSignal(
                datetime=row["datetime"],
                direction=Direction.BUY,
                entry_price=entry,
                stop_loss=sl,
                take_profit=tp,
                initial_risk=risk,
                or_high=or_h,
                or_low=or_l,
                or_range=or_rng
            )

        # Sinyal Short
        elif row["low"] < or_l:
            if htf_filter_active and row["close"] > htf_ema:
                return None
            entry = or_l
            risk = or_rng
            sl = entry + risk
            tp = entry - risk * cfg.TARGET_RR
            return NYSignal(
                datetime=row["datetime"],
                direction=Direction.SELL,
                entry_price=entry,
                stop_loss=sl,
                take_profit=tp,
                initial_risk=risk,
                or_high=or_h,
                or_low=or_l,
                or_range=or_rng
            )

        return None

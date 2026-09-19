"""
London Pit Opening Range Breakout (London Pit ORB) — Strategy & Signal Generation
==================================================================================
Logika kuantitatif London Pit ORB:
- Pembentukan Opening Range: 08:00 - 08:15 UTC (3 bar M5, saat bursa London buka)
- Jendela Eksekusi: 08:15 - 11:30 UTC
- Filter Ekspansi: True Range (TR) candle sebelumnya > 1.5 x SMA(20) TR (100% Kausal)
- Stop Loss: lor_range penuh (batas seberang)
- Take Profit: 2.0R (entry +/- 2.0 * lor_range)
- Entry Level: lor_high (Long) atau lor_low (Short)
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional
import numpy as np
import pandas as pd

from configs import london_config as cfg


class Direction(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


@dataclass
class LondonSignal:
    """Representasi sinyal entri London Pit ORB."""
    datetime: pd.Timestamp
    direction: Direction
    entry_price: float
    stop_loss: float
    take_profit: float
    initial_risk: float
    lor_high: float
    lor_low: float
    lor_range: float
    lot_size: float = 0.0


def compute_london_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Hitung True Range (TR), SMA20 TR, ATR14, dan identifikasi London Opening Range M15 (08:00 - 08:15 UTC).
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

    # 2. Extract London Opening Range M15 (08:00 - 08:15 UTC) per date
    df["date"] = df["datetime"].dt.date
    dow = df["datetime"].dt.dayofweek
    # Normalize Sunday bars to Monday session
    df.loc[dow == 6, "date"] = (df.loc[dow == 6, "datetime"] + pd.Timedelta(days=1)).dt.date

    df["hour"] = df["datetime"].dt.hour
    df["minute"] = df["datetime"].dt.minute

    # 08:00 <= time < 08:15
    lor_mask = (df["hour"] == 8) & (df["minute"] >= 0) & (df["minute"] < 15)
    lor_bars = df[lor_mask]

    lor_summary = lor_bars.groupby("date").agg(
        lor_high=("high", "max"),
        lor_low=("low", "min"),
        bar_count=("close", "count")
    ).reset_index()

    lor_summary["lor_range"] = lor_summary["lor_high"] - lor_summary["lor_low"]
    valid_lor = lor_summary[(lor_summary["bar_count"] >= cfg.MIN_LORB_BARS) & (lor_summary["lor_range"] > 0)]

    df = df.merge(valid_lor[["date", "lor_high", "lor_low", "lor_range"]], on="date", how="left")
    return df


class LondonStrategy:
    """Evaluator aturan kuantitatif London Pit ORB."""

    def __init__(self):
        pass

    def evaluate_bar(self, row: pd.Series) -> Optional[LondonSignal]:
        """
        Evaluasi satu bar M5 untuk mencari peluang entri penembusan London Pit ORB.
        """
        h_time = (row["hour"], row["minute"])
        # Jendela evaluasi: (8, 15) <= h_time < (11, 30)
        if h_time < (8, 15) or h_time >= (11, 30):
            return None

        lor_h = row["lor_high"]
        lor_l = row["lor_low"]
        lor_rng = row["lor_range"]

        if pd.isna(lor_h) or pd.isna(lor_l) or pd.isna(lor_rng) or lor_rng <= 0:
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
        if row["high"] > lor_h:
            if htf_filter_active and row["close"] < htf_ema:
                return None
            entry = lor_h
            risk = lor_rng
            sl = entry - risk
            tp = entry + risk * cfg.TARGET_RR
            return LondonSignal(
                datetime=row["datetime"],
                direction=Direction.BUY,
                entry_price=entry,
                stop_loss=sl,
                take_profit=tp,
                initial_risk=risk,
                lor_high=lor_h,
                lor_low=lor_l,
                lor_range=lor_rng
            )

        # Sinyal Short
        elif row["low"] < lor_l:
            if htf_filter_active and row["close"] > htf_ema:
                return None
            entry = lor_l
            risk = lor_rng
            sl = entry + risk
            tp = entry - risk * cfg.TARGET_RR
            return LondonSignal(
                datetime=row["datetime"],
                direction=Direction.SELL,
                entry_price=entry,
                stop_loss=sl,
                take_profit=tp,
                initial_risk=risk,
                lor_high=lor_h,
                lor_low=lor_l,
                lor_range=lor_rng
            )

        return None

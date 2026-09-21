"""
London Pit Opening Range Breakout (London Pit ORB) — Strategy & Canonical Signals
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
from typing import Optional, Tuple, List, Dict, Any
from datetime import datetime
import pandas as pd
import numpy as np

from src.core.types import Direction, OrderIntent, ExitIntent
from src.core.indicators import calc_true_range
from . import config as cfg


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

    # 1. True Range & SMA20 TR
    tr = calc_true_range(df)
    df["tr"] = tr
    df["tr_past"] = df["tr"].shift(1)
    df["tr_sma20"] = df["tr"].rolling(cfg.EXPANSION_SMA_PERIOD).mean().shift(1)
    df["atr14"] = df["tr"].ewm(alpha=1.0 / 14, adjust=False).mean()

    # 2. Extract London Opening Range M15 (08:00 - 08:15 UTC) per date
    df["date"] = df["datetime"].dt.date
    dow = df["datetime"].dt.dayofweek
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


def form_london_or_box(df_day: pd.DataFrame, or_start: Tuple[int, int] = (8, 0), or_end: Tuple[int, int] = (8, 15)) -> Optional[Tuple[float, float, float]]:
    """
    Kanonikal helper pembentukan box Opening Range London untuk live executor.
    Mengembalikan (high, low, range) jika valid, None jika bar belum cukup.
    """
    or_h, or_m = or_start
    lor_bars = df_day[(df_day["datetime"].dt.hour == or_h) & (df_day["datetime"].dt.minute >= or_m) & (df_day["datetime"].dt.minute < or_end[1])]
    if len(lor_bars) >= cfg.MIN_LORB_BARS:
        or_high = float(lor_bars["high"].max())
        or_low = float(lor_bars["low"].min())
        or_range = or_high - or_low
        if or_range > 0:
            return or_high, or_low, or_range
    return None


def evaluate_london_breakout(
    ask: float,
    bid: float,
    spread: float,
    or_high: float,
    or_low: float,
    or_range: float,
    prior_tr: float,
    prior_tr_sma20: float,
    max_spread: float = 0.60,
    max_chase: float = 0.80,
    target_rr: float = 2.0,
    expansion_mult: float = 1.5,
) -> Optional[dict]:
    """
    Kanonikal evaluator sinyal breakout London untuk mode live (IOC fast-tick).
    Mengembalikan dict sinyal jika breakout valid, atau dict rejected dengan status jika anti-chasing/spread block.
    """
    # 1. Filter volatilitas ekspansi (100% Causal)
    if pd.isna(prior_tr_sma20) or prior_tr_sma20 <= 0 or prior_tr <= expansion_mult * prior_tr_sma20:
        return None

    # 2. Long Breakout
    if ask > or_high:
        if ask > or_high + max_chase:
            return {"status": "CHASE_BLOCKED", "direction": Direction.BUY, "limit": or_high + max_chase}
        if spread > max_spread:
            return {"status": "SPREAD_BLOCKED", "spread": spread}

        sl = or_low
        tp = or_high + or_range * target_rr
        return {
            "status": "VALID",
            "direction": Direction.BUY,
            "entry_price": ask,
            "sl": sl,
            "tp": tp,
            "risk": or_range,
        }

    # 3. Short Breakout
    if bid < or_low:
        if bid < or_low - max_chase:
            return {"status": "CHASE_BLOCKED", "direction": Direction.SELL, "limit": or_low - max_chase}
        if spread > max_spread:
            return {"status": "SPREAD_BLOCKED", "spread": spread}

        sl = or_high
        tp = or_low - or_range * target_rr
        return {
            "status": "VALID",
            "direction": Direction.SELL,
            "entry_price": bid,
            "sl": sl,
            "tp": tp,
            "risk": or_range,
        }

    return None


class LondonStrategy:
    """Evaluator aturan kuantitatif London Pit ORB untuk backtesting bar-by-bar."""

    def evaluate_bar(self, row: pd.Series) -> Optional[LondonSignal]:
        h_time = (row["hour"], row["minute"])
        if h_time < (8, 15) or h_time >= (11, 30):
            return None

        lor_h = row["lor_high"]
        lor_l = row["lor_low"]
        lor_rng = row["lor_range"]

        if pd.isna(lor_h) or pd.isna(lor_l) or pd.isna(lor_rng) or lor_rng <= 0:
            return None

        # Filter Ekspansi
        if cfg.USE_EXPANSION_FILTER:
            tr = row["tr_past"]
            tr_sma = row["tr_sma20"]
            if pd.isna(tr_sma) or tr_sma <= 0 or tr <= cfg.EXPANSION_MULT * tr_sma:
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


# ─────────────────────────────────────────────
# CANONICAL LIVE INTENT EVALUATION
# ─────────────────────────────────────────────

def evaluate_london_exit(
    position: Any,
    now_utc: datetime,
    cutoff_hm: Tuple[int, int] = (11, 25),
) -> Optional[ExitIntent]:
    """
    Kanonikal evaluator exit untuk posisi aktif London ORB.
    Memeriksa session cutoff (11:25 UTC).
    """
    ticket = getattr(position, "ticket", 0)
    profit = getattr(position, "profit", 0.0)
    hm = (now_utc.hour, now_utc.minute)

    if hm >= cutoff_hm:
        return ExitIntent(
            ticket=ticket,
            should_exit=True,
            reason=f"Session Cutoff London ({cutoff_hm[0]:02d}:{cutoff_hm[1]:02d} UTC)",
            comment="Cutoff-London",
            strategy_id="LONDON",
        )
    return None


def evaluate_london_entry(
    df_m5: pd.DataFrame,
    tick: Dict[str, Any],
    equity: float,
    now_utc: datetime,
    sched: Dict[str, Any],
    or_high: Optional[float],
    or_low: Optional[float],
    or_range: Optional[float],
    risk_pct: float = 0.02,
    point_value: float = 100.0,
    lot_step: float = 0.01,
    min_lot: float = 0.01,
    max_lot: float = 10.0,
    max_spread: float = 0.60,
    max_chase: float = 0.80,
    target_rr: float = 2.0,
    expansion_mult: float = 1.5,
) -> Optional[dict]:
    """
    Kanonikal evaluator entry untuk London Pit ORB.
    Domain murni: menghasilkan dict dengan status dan OrderIntent jika kondisi entry terpenuhi.
    """
    if or_high is None or or_low is None or or_range is None or or_range <= 0:
        return None

    hm = (now_utc.hour, now_utc.minute)
    entry_start = sched.get("LONDON_ENTRY_START", (8, 15))
    entry_end = sched.get("LONDON_ENTRY_END", (11, 30))
    if not (entry_start <= hm < entry_end):
        return None

    risk_usd = equity * risk_pct
    raw_lot = risk_usd / (or_range * point_value)
    lot = max(min_lot, min(round(raw_lot / lot_step) * lot_step, max_lot))
    lot = round(lot, 2)

    # Hitung prior TR dan prior TR SMA20
    prev_close = df_m5["close"].shift(1)
    tr1 = df_m5["high"] - df_m5["low"]
    tr2 = (df_m5["high"] - prev_close).abs()
    tr3 = (df_m5["low"] - prev_close).abs()
    tr_series = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    prior_tr = tr_series.iloc[-2]
    prior_tr_sma20 = tr_series.iloc[:-1].rolling(20).mean().iloc[-1]

    breakout_res = evaluate_london_breakout(
        ask=tick["ask"],
        bid=tick["bid"],
        spread=tick.get("spread", 0.0),
        or_high=or_high,
        or_low=or_low,
        or_range=or_range,
        prior_tr=prior_tr,
        prior_tr_sma20=prior_tr_sma20,
        max_spread=max_spread,
        max_chase=max_chase,
        target_rr=target_rr,
        expansion_mult=expansion_mult,
    )

    if breakout_res is None:
        return None

    if breakout_res["status"] == "CHASE_BLOCKED":
        return {
            "status": "CHASE_BLOCKED",
            "message": f"Harga sudah melompat > ${max_chase:.2f} dari OR. Dibatalkan demi keamanan.",
            "intent": None,
        }

    if breakout_res["status"] == "SPREAD_BLOCKED":
        return {
            "status": "SPREAD_BLOCKED",
            "message": f"Spread ({breakout_res['spread']:.2f}) > limit ({max_spread:.2f})",
            "intent": None,
        }

    if breakout_res["status"] == "VALID":
        intent = OrderIntent(
            strategy_id="LONDON",
            action=breakout_res["direction"].value,
            volume=lot,
            entry_price=breakout_res["entry_price"],
            stop_loss=breakout_res["sl"],
            take_profit=breakout_res["tp"],
            comment="London-ORB-FLG",
            magic_number=888001,
            metadata={
                "or_high": or_high,
                "or_low": or_low,
                "or_range": or_range,
                "risk_usd": risk_usd,
            },
        )
        return {
            "status": "VALID",
            "intent": intent,
        }

    return None

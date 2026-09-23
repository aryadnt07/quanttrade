"""
New York Opening Range Breakout (NY ORB) — Strategy & Canonical Signals
========================================================================
Logika kuantitatif New York ORB:
- Pembentukan Opening Range: 13:30 - 13:45 UTC (Dynamic DST)
- Jendela Eksekusi: 13:45 - 16:30 UTC
- Filter Ekspansi: True Range (TR) candle sebelumnya > 1.5 x SMA(20) TR (100% Kausal)
- Stop Loss: or_range penuh (batas seberang)
- Take Profit: 2.0R (entry +/- 2.0 * or_range)
- Entry Level: or_high (Long) atau or_low (Short)
"""

from dataclasses import dataclass
from typing import Optional, Tuple, List, Dict, Any
from datetime import datetime
import numpy as np
import pandas as pd

from src.core.types import Direction, OrderIntent, ExitIntent
from src.core.indicators import calc_true_range
from . import config as cfg


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

    # 1. True Range & SMA20 TR
    tr = calc_true_range(df)
    df["tr"] = tr
    df["tr_past"] = df["tr"].shift(1)
    df["tr_sma20"] = df["tr"].rolling(cfg.EXPANSION_SMA_PERIOD).mean().shift(1)
    df["atr14"] = df["tr"].ewm(alpha=1.0 / 14, adjust=False).mean()

    # 2. Extract Opening Range M15 (09:30-09:45 ET / 13:30/14:30 UTC) per date
    df["date"] = df["datetime"].dt.date
    df["hour"] = df["datetime"].dt.hour
    df["minute"] = df["datetime"].dt.minute

    if getattr(cfg, "USE_DYNAMIC_DST", True):
        # Wall Street Open is 09:30 - 09:45 in America/New_York local time year-round
        ny_times = df["datetime"].dt.tz_convert("America/New_York")
        or_mask = (ny_times.dt.hour == 9) & (ny_times.dt.minute >= 30) & (ny_times.dt.minute < 45)
    else:
        # Static UTC: 13:30 <= time < 13:45 UTC
        or_mask = (df["hour"] == 13) & (df["minute"] >= 30) & (df["minute"] < 45)
    or_bars = df[or_mask]

    or_summary = or_bars.groupby("date").agg(
        or_high=("high", "max"),
        or_low=("low", "min"),
        bar_count=("close", "count")
    ).reset_index()

    or_summary["or_range"] = or_summary["or_high"] - or_summary["or_low"]
    valid_or = or_summary[(or_summary["bar_count"] >= cfg.MIN_ORB_BARS) & (or_summary["or_range"] > 0)]

    df = df.merge(valid_or[["date", "or_high", "or_low", "or_range"]], on="date", how="left")
    return df


def form_ny_or_box(df_day: pd.DataFrame, or_start: Tuple[int, int] = (13, 30), or_end: Tuple[int, int] = (13, 45)) -> Optional[Tuple[float, float, float]]:
    """
    Kanonikal helper pembentukan box Opening Range New York untuk live executor.
    Mengembalikan (high, low, range) jika valid, None jika bar belum cukup.
    """
    or_h, or_m = or_start
    ny_bars = df_day[(df_day["datetime"].dt.hour == or_h) & (df_day["datetime"].dt.minute >= or_m) & (df_day["datetime"].dt.minute < or_end[1])]
    if len(ny_bars) >= cfg.MIN_ORB_BARS:
        or_high = float(ny_bars["high"].max())
        or_low = float(ny_bars["low"].min())
        or_range = or_high - or_low
        if or_range > 0:
            return or_high, or_low, or_range
    return None


def evaluate_ny_breakout(
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
    Kanonikal evaluator sinyal breakout New York untuk mode live (IOC fast-tick).
    """
    if pd.isna(prior_tr_sma20) or prior_tr_sma20 <= 0 or prior_tr <= expansion_mult * prior_tr_sma20:
        return None

    # Long Breakout
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

    # Short Breakout
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


class NYStrategy:
    """Evaluator aturan kuantitatif New York ORB untuk backtesting bar-by-bar."""

    def evaluate_bar(self, row: pd.Series) -> Optional[NYSignal]:
        h_time = (row["hour"], row["minute"])
        if h_time < (13, 45) or h_time >= (16, 30):
            return None

        or_h = row["or_high"]
        or_l = row["or_low"]
        or_rng = row["or_range"]

        if pd.isna(or_h) or pd.isna(or_l) or pd.isna(or_rng) or or_rng <= 0:
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


# ─────────────────────────────────────────────
# CANONICAL LIVE INTENT EVALUATION
# ─────────────────────────────────────────────

def evaluate_ny_exit(
    position: Any,
    now_utc: datetime,
    cutoff_hm: Tuple[int, int] = (16, 25),
) -> Optional[ExitIntent]:
    """
    Kanonikal evaluator exit untuk posisi aktif New York ORB.
    Memeriksa session cutoff (16:25 UTC / 12:25 NY Local).
    """
    ticket = getattr(position, "ticket", 0)
    profit = getattr(position, "profit", 0.0)
    hm = (now_utc.hour, now_utc.minute)

    if hm >= cutoff_hm:
        return ExitIntent(
            ticket=ticket,
            should_exit=True,
            reason=f"Session Cutoff NY ({cutoff_hm[0]:02d}:{cutoff_hm[1]:02d} UTC)",
            comment="Cutoff-NY",
            strategy_id="NY",
        )
    return None


def evaluate_ny_entry(
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
    Kanonikal evaluator entry untuk New York ORB.
    Domain murni: menghasilkan dict dengan status dan OrderIntent jika kondisi entry terpenuhi.
    """
    if or_high is None or or_low is None or or_range is None or or_range <= 0:
        return None

    hm = (now_utc.hour, now_utc.minute)
    entry_start = sched.get("NY_ENTRY_START", (14, 45))
    entry_end = sched.get("NY_ENTRY_END", (17, 30))
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

    breakout_res = evaluate_ny_breakout(
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
        direction = breakout_res.get("direction", Direction.BUY)
        limit_entry = or_high if direction == Direction.BUY else or_low
        sl = or_low if direction == Direction.BUY else or_high
        tp_dist = or_range * target_rr
        tp = limit_entry + tp_dist if direction == Direction.BUY else limit_entry - tp_dist
        action = "BUY_LIMIT" if direction == Direction.BUY else "SELL_LIMIT"
        
        intent = OrderIntent(
            strategy_id="NY",
            action=action,
            volume=lot,
            entry_price=limit_entry,
            stop_loss=sl,
            take_profit=tp,
            comment="NY-Limit-FLG",
            magic_number=888001,
            metadata={
                "or_high": or_high,
                "or_low": or_low,
                "or_range": or_range,
                "risk_usd": risk_usd,
            },
        )
        return {
            "status": "CHASE_BLOCKED",
            "message": f"Harga loncat > ${max_chase:.2f}. Beralih ke Limit Order di {limit_entry:.2f}.",
            "intent": intent,
        }

    if breakout_res["status"] == "SPREAD_BLOCKED":
        return {
            "status": "SPREAD_BLOCKED",
            "message": f"Spread ({breakout_res['spread']:.2f}) > limit ({max_spread:.2f})",
            "intent": None,
        }

    if breakout_res["status"] == "VALID":
        intent = OrderIntent(
            strategy_id="NY",
            action=breakout_res["direction"].value,
            volume=lot,
            entry_price=breakout_res["entry_price"],
            stop_loss=breakout_res["sl"],
            take_profit=breakout_res["tp"],
            comment="NY-ORB-FLG",
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

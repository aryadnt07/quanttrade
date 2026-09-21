"""
Asian Mean Reversion — Canonical Signal & Indicator Generator
==============================================================
Logika kuantitatif sinyal entry & exit Asian MR berbasis Z-Score, RSI, dan filter volatilitas ATR.
Digunakan secara bersama oleh modul Backtest dan Live Execution.
"""

from typing import Optional, Tuple, Dict, Any
from datetime import datetime
import numpy as np
import pandas as pd

from src.core.types import Direction, ExitReason, Signal, OrderIntent, ExitIntent
from src.core.indicators import (
    calc_sma,
    calc_session_vwap,
    calc_rolling_std,
    calc_zscore,
    calc_rsi,
    calc_atr,
    calc_atr_sma,
    calc_adx,
    calc_htf_ema,
)
from . import config as cfg


# ─────────────────────────────────────────────
# 1. PIPELINE INDIKATOR ASIA
# ─────────────────────────────────────────────

def compute_asian_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Hitung semua indikator sesi Asia pada DataFrame M5."""
    df = df.copy()
    df.sort_values("datetime", inplace=True)
    df.reset_index(drop=True, inplace=True)

    session_labels = df["datetime"].dt.date if cfg.USE_VWAP else None

    # 1. Anchor (Mean)
    if cfg.USE_VWAP and "volume" in df.columns and session_labels is not None:
        df["anchor"] = calc_session_vwap(df, session_labels)
    else:
        df["anchor"] = calc_sma(df["close"], cfg.ROLLING_WINDOW)

    # 2. Standar deviasi
    df["std"] = calc_rolling_std(df["close"], cfg.ROLLING_WINDOW, cfg.MIN_SIGMA)

    # 3. Z-Score
    df["zscore"] = calc_zscore(df["close"], df["anchor"], df["std"])

    # 4. RSI
    df["rsi"] = calc_rsi(df["close"], cfg.RSI_PERIOD)

    # 5. ATR & ATR SMA
    df["atr"] = calc_atr(df, cfg.ATR_PERIOD)
    df["atr_sma"] = calc_atr_sma(df["atr"], cfg.ATR_SMA_PERIOD)

    # 6. ADX
    df["adx"] = calc_adx(df, cfg.ADX_PERIOD)

    # 7. HTF EMA (H1 EMA 200)
    if getattr(cfg, "USE_HTF_TREND_FILTER", False):
        if "h1_ema200" in df.columns:
            df["htf_ema"] = df["h1_ema200"]
        elif "htf_ema" not in df.columns:
            htf_tf = getattr(cfg, "HTF_TIMEFRAME", "1h")
            htf_p = getattr(cfg, "HTF_EMA_PERIOD", 200)
            df["htf_ema"] = calc_htf_ema(df, htf=htf_tf, period=htf_p)

    # 8. Band visualisasi
    df["upper_band"] = df["anchor"] + (cfg.Z_ENTRY_THRESHOLD * df["std"])
    df["lower_band"] = df["anchor"] - (cfg.Z_ENTRY_THRESHOLD * df["std"])

    return df


# ─────────────────────────────────────────────
# 2. CANDLE CONFIRMATION HELPERS
# ─────────────────────────────────────────────

def _is_bearish_candle(row: pd.Series) -> bool:
    return row["close"] < row["open"]


def _is_bullish_candle(row: pd.Series) -> bool:
    return row["close"] > row["open"]


def is_in_entry_window(dt: pd.Timestamp) -> bool:
    """Cek apakah waktu berada dalam jendela entri (01:00-04:30 UTC)."""
    start_h, start_m = map(int, cfg.SESSION_ENTRY_START.split(":"))
    end_h, end_m = map(int, cfg.SESSION_ENTRY_END.split(":"))
    current_minutes = dt.hour * 60 + dt.minute
    return (start_h * 60 + start_m) <= current_minutes < (end_h * 60 + end_m)


def passes_volatility_filter(atr: float, atr_sma: float) -> bool:
    """Filter volatilitas gerbang bawah & gerbang atas."""
    if pd.isna(atr) or pd.isna(atr_sma):
        return False
    if atr < cfg.ATR_MIN_THRESHOLD:
        return False
    if atr > (cfg.ATR_ANOMALY_MULTIPLIER * atr_sma):
        return False
    return True


def calculate_lot_size(entry_price: float, sl: float) -> float:
    """Hitung lot dinamis berbasis fixed dollar risk."""
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
    return max(getattr(cfg, "MIN_LOT", 0.01), min(lot, getattr(cfg, "MAX_LOT", 2.0)))


# ─────────────────────────────────────────────
# 3. SIGNAL GENERATION (ENTRY)
# ─────────────────────────────────────────────

def check_entry_signal(row: pd.Series, idx: int) -> Optional[Signal]:
    """Evaluasi bar saat ini untuk sinyal entry (LONG atau SHORT)."""
    if not is_in_entry_window(row["datetime"]):
        return None

    atr = row.get("atr")
    atr_sma = row.get("atr_sma")
    if not passes_volatility_filter(atr, atr_sma):
        return None

    zscore = row.get("zscore")
    rsi = row.get("rsi")
    close = row.get("close")

    if pd.isna(zscore) or pd.isna(rsi) or pd.isna(atr) or pd.isna(close):
        return None

    rsi_short_valid = (not getattr(cfg, "USE_RSI_FILTER", True)) or (rsi >= cfg.RSI_OVERBOUGHT)
    rsi_long_valid = (not getattr(cfg, "USE_RSI_FILTER", True)) or (rsi <= cfg.RSI_OVERSOLD)

    short_htf_ok = True
    long_htf_ok = True
    if getattr(cfg, "USE_HTF_TREND_FILTER", False):
        htf_ema = row.get("htf_ema")
        if pd.notna(htf_ema):
            mode = getattr(cfg, "HTF_FILTER_MODE", "SYMMETRIC")
            if mode == "SYMMETRIC":
                short_htf_ok = close < htf_ema
                long_htf_ok = close > htf_ema
            elif mode == "ASYMMETRIC_LONG_ONLY":
                short_htf_ok = True
                long_htf_ok = close > htf_ema

    # SHORT SIGNAL
    if zscore >= cfg.Z_ENTRY_THRESHOLD and rsi_short_valid and short_htf_ok:
        if not cfg.REQUIRE_OPPOSING_CLOSE or _is_bearish_candle(row):
            entry_price = close
            sl = entry_price + (atr * cfg.ATR_SL_MULTIPLIER)
            tp = row["anchor"]
            lot = calculate_lot_size(entry_price, sl)
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
                initial_risk=abs(entry_price - sl),
            )

    # LONG SIGNAL
    if zscore <= -cfg.Z_ENTRY_THRESHOLD and rsi_long_valid and long_htf_ok:
        if not cfg.REQUIRE_OPPOSING_CLOSE or _is_bullish_candle(row):
            entry_price = close
            sl = entry_price - (atr * cfg.ATR_SL_MULTIPLIER)
            tp = row["anchor"]
            lot = calculate_lot_size(entry_price, sl)
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
                initial_risk=abs(entry_price - sl),
            )

    return None


# ─────────────────────────────────────────────
# 4. EXIT EVALUATION (CANONICAL)
# ─────────────────────────────────────────────

def check_exit_conditions(
    row: pd.Series,
    signal: Signal,
) -> Optional[ExitReason]:
    """Evaluasi apakah posisi terbuka harus ditutup pada bar ini."""
    dt = row["datetime"]
    high = row["high"]
    low = row["low"]
    zscore = row.get("zscore", 0.0)

    # Session Cutoff
    time_str = dt.strftime("%H:%M")
    if time_str >= cfg.SESSION_HARD_CUTOFF or dt.date() != signal.datetime.date():
        return ExitReason.SESSION_CUTOFF

    end_h, end_m = map(int, cfg.SESSION_HARD_CUTOFF.split(":"))
    if (dt.hour * 60 + dt.minute) >= (end_h * 60 + end_m - 5):
        return ExitReason.SESSION_CUTOFF

    # Time-stop 60 menit
    duration = (dt - signal.datetime).total_seconds() / 60.0
    if duration >= cfg.MAX_TRADE_DURATION_MIN:
        return ExitReason.TIME_STOP

    # Emergency Hard Cut (|Z| >= 3.2)
    if signal.direction.is_short and zscore >= cfg.Z_HARD_CUT:
        return ExitReason.HARD_CUT_Z
    if signal.direction.is_long and zscore <= -cfg.Z_HARD_CUT:
        return ExitReason.HARD_CUT_Z

    # Hard Take Profit (Limit Order TP di server MT5)
    if signal.take_profit is not None:
        if signal.direction.is_long and high >= signal.take_profit:
            return ExitReason.TAKE_PROFIT
        if signal.direction.is_short and low <= signal.take_profit:
            return ExitReason.TAKE_PROFIT

    # Stop Loss (dengan simulasi Ask Spread untuk SHORT)
    spread = getattr(cfg, "SPREAD_USD", 0.30)
    if signal.direction.is_short and (high + spread) >= signal.stop_loss:
        return ExitReason.STOP_LOSS
    if signal.direction.is_long and low <= signal.stop_loss:
        return ExitReason.STOP_LOSS

    # Take Profit: Z-Score kembali ke area netral [-0.5, 0.5]
    if -cfg.Z_EXIT_THRESHOLD <= zscore <= cfg.Z_EXIT_THRESHOLD:
        return ExitReason.TAKE_PROFIT_Z


    return None


def get_exit_price(
    row: pd.Series,
    signal: Signal,
    reason: ExitReason,
) -> float:
    """Tentukan harga exit berdasarkan alasan exit."""
    if reason in (ExitReason.STOP_LOSS, ExitReason.STOP_LOSS_ATR):
        return signal.stop_loss
    if reason in (ExitReason.TAKE_PROFIT, ExitReason.TAKE_PROFIT_Z) and signal.take_profit is not None:
        return signal.take_profit
    return row["close"]


# ─────────────────────────────────────────────
# 5. CANONICAL LIVE INTENT EVALUATION (STANDARDIZED PROTOCOL)
# ─────────────────────────────────────────────

def evaluate_asian_exit(
    position: Any,
    df_m5: pd.DataFrame,
    now_utc: datetime,
    broker_utc_offset_sec: int = 0,
    cutoff_hm: Tuple[int, int] = (6, 0),
    max_duration_min: float = 60.0,
    z_hard_cut: float = 3.2,
    z_exit_thresh: float = 0.5,
    indicator_func: Optional[Any] = None,
) -> Optional[ExitIntent]:
    """
    Kanonikal evaluator exit untuk posisi aktif Asian Mean Reversion.
    Domain murni: menghasilkan ExitIntent jika posisi harus ditutup.
    """
    ticket = getattr(position, "ticket", 0)
    profit = getattr(position, "profit", 0.0)
    pos_type = getattr(position, "type", 0)
    pos_time = getattr(position, "time", 0)
    is_buy = (pos_type == 0)  # mt5.ORDER_TYPE_BUY = 0

    hm = (now_utc.hour, now_utc.minute)

    # 1. Hard Cutoff 06:00 UTC
    if hm >= cutoff_hm:
        return ExitIntent(
            ticket=ticket,
            should_exit=True,
            reason=f"Session Cutoff ({cutoff_hm[0]:02d}:{cutoff_hm[1]:02d} UTC)",
            comment="Cutoff-06:00",
            strategy_id="ASIAN",
        )

    # 2. Time Stop (60 Menit)
    pos_open_utc_ts = pos_time - broker_utc_offset_sec
    duration_min = (now_utc.timestamp() - pos_open_utc_ts) / 60.0
    if duration_min >= max_duration_min:
        return ExitIntent(
            ticket=ticket,
            should_exit=True,
            reason=f"Time-Stop ({duration_min:.1f}m >= {max_duration_min:.0f}m)",
            comment="TimeStop-60m",
            strategy_id="ASIAN",
        )

    # Dapatkan indikator Asia
    if indicator_func is None:
        import sys
        runner_mod = sys.modules.get("src.execution.runner") or sys.modules.get("live.live_runner")
        indicator_func = getattr(runner_mod, "compute_asian_indicators", compute_asian_indicators)

    df_asia = indicator_func(df_m5)
    if df_asia is None or len(df_asia) == 0:
        return None

    latest_z = float(df_asia["zscore"].iloc[-2]) if len(df_asia) >= 2 else float(df_asia["zscore"].iloc[-1])

    # 3. Emergency Hard Cut (|Z| >= 3.2)
    if (is_buy and latest_z <= -z_hard_cut) or (not is_buy and latest_z >= z_hard_cut):
        return ExitIntent(
            ticket=ticket,
            should_exit=True,
            reason=f"Hard-Cut Ekstrim (|Z|={abs(latest_z):.2f} >= {z_hard_cut})",
            comment="HardCut-Z3.2",
            strategy_id="ASIAN",
        )

    # 4. Take Profit: Z-Score Mean Reversion ([-0.5, 0.5])
    if is_buy and latest_z >= -z_exit_thresh:
        return ExitIntent(
            ticket=ticket,
            should_exit=True,
            reason=f"TP Mean-Reversion Z-Neutral ({latest_z:.2f} >= -{z_exit_thresh})",
            comment="TP-Z-Neutral",
            strategy_id="ASIAN",
        )
    elif not is_buy and latest_z <= z_exit_thresh:
        return ExitIntent(
            ticket=ticket,
            should_exit=True,
            reason=f"TP Mean-Reversion Z-Neutral ({latest_z:.2f} <= +{z_exit_thresh})",
            comment="TP-Z-Neutral",
            strategy_id="ASIAN",
        )

    return None


def evaluate_asian_entry(
    df_m5: pd.DataFrame,
    tick: Dict[str, Any],
    equity: float,
    now_utc: datetime,
    sched: Dict[str, Any],
    risk_pct: float = 0.01,
    max_spread: float = 0.60,
    point_value: float = 100.0,
    lot_step: float = 0.01,
    min_lot: float = 0.01,
    max_lot: float = 10.0,
    symbol_stops_level: float = 0.30,
    indicator_func: Optional[Any] = None,
    entry_func: Optional[Any] = None,
) -> Optional[OrderIntent]:
    """
    Kanonikal evaluator entry untuk Asian Mean Reversion.
    Domain murni: menghasilkan OrderIntent jika kondisi entry terpenuhi.
    """
    hm = (now_utc.hour, now_utc.minute)
    if not (sched.get("ASIAN_START", (1, 0)) <= hm < sched.get("ASIAN_END", (4, 30))):
        return None

    if indicator_func is None:
        import sys
        runner_mod = sys.modules.get("src.execution.runner") or sys.modules.get("live.live_runner")
        indicator_func = getattr(runner_mod, "compute_asian_indicators", compute_asian_indicators)

    if entry_func is None:
        import sys
        runner_mod = sys.modules.get("src.execution.runner") or sys.modules.get("live.live_runner")
        entry_func = getattr(runner_mod, "check_asian_entry", check_entry_signal)

    df_asia = indicator_func(df_m5)
    if df_asia is None or len(df_asia) == 0:
        return None

    eval_row = df_asia.iloc[-2] if len(df_asia) >= 2 else df_asia.iloc[-1]
    sig = entry_func(eval_row, len(df_asia) - 2)
    if sig is None:
        return None

    # Proteksi Spread
    if tick.get("spread", 0.0) > max_spread:
        return None

    risk_usd = equity * risk_pct
    sl_dist = abs(sig.entry_price - sig.stop_loss)
    if sl_dist <= 0:
        return None

    raw_lot = risk_usd / (sl_dist * point_value)
    lot = max(min_lot, min(round(raw_lot / lot_step) * lot_step, max_lot))
    lot = round(lot, 2)

    dir_str = "BUY" if sig.direction.is_long else "SELL"

    # Validasi TP & Stops Level
    tp_val = sig.take_profit
    if dir_str == "BUY":
        if tp_val is not None and tp_val <= tick["ask"] + symbol_stops_level:
            tp_val = None
    else:
        if tp_val is not None and tp_val >= tick["bid"] - symbol_stops_level:
            tp_val = None

    return OrderIntent(
        strategy_id="ASIAN",
        action=dir_str,
        volume=lot,
        entry_price=sig.entry_price,
        stop_loss=sig.stop_loss,
        take_profit=tp_val,
        comment="AsiaMR-FLG",
        magic_number=888001,
        metadata={
            "zscore": sig.zscore,
            "rsi": sig.rsi,
            "atr": sig.atr,
            "risk_usd": risk_usd,
        },
    )

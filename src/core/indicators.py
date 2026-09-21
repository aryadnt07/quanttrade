"""
Core Mathematical Indicators & Oscillators
==========================================
Pure, stateless mathematical implementations of quantitative indicators:
SMA, EMA, VWAP, Rolling Std Dev, Z-Score, RSI (Wilder), True Range, ATR, ADX, HTF EMA.
Zero external framework dependencies (pure NumPy & Pandas).
"""

from typing import Optional
import numpy as np
import pandas as pd


# ─────────────────────────────────────────────────────────────
# 1. MOVING AVERAGES & ANCHORS
# ─────────────────────────────────────────────────────────────

def calc_sma(series: pd.Series, period: int = 20) -> pd.Series:
    """Simple Moving Average (SMA)."""
    return series.rolling(window=period, min_periods=period).mean()


def calc_ema(series: pd.Series, span: int = 20) -> pd.Series:
    """Exponential Moving Average (EMA)."""
    return series.ewm(span=span, adjust=False).mean()


def calc_session_vwap(df: pd.DataFrame, session_labels: pd.Series) -> pd.Series:
    """Session VWAP — terakumulasi dan reset berdasarkan session_labels."""
    typical_price = (df["high"] + df["low"] + df["close"]) / 3.0
    tp_vol = typical_price * df["volume"]

    cum_tp_vol = tp_vol.groupby(session_labels).cumsum()
    cum_vol = df["volume"].groupby(session_labels).cumsum()

    return cum_tp_vol / cum_vol.replace(0, np.nan)


# ─────────────────────────────────────────────────────────────
# 2. VOLATILITY & STATISTICAL METRICS
# ─────────────────────────────────────────────────────────────

def calc_rolling_std(
    series: pd.Series,
    period: int = 20,
    min_sigma: float = 0.001,
) -> pd.Series:
    """Sample rolling standard deviation dengan proteksi zero-division."""
    std = series.rolling(window=period, min_periods=period).std(ddof=1)
    return std.clip(lower=min_sigma)


def calc_zscore(
    price: pd.Series,
    mean: pd.Series,
    std: pd.Series,
) -> pd.Series:
    """Z-Score normalisasi deviasi harga dari nilai tengah."""
    return (price - mean) / std


def calc_true_range(df: pd.DataFrame) -> pd.Series:
    """
    True Range standar Welles Wilder:
    TR_t = max(H - L, |H - C_{t-1}|, |L - C_{t-1}|)
    """
    high = df["high"]
    low = df["low"]
    prev_close = df["close"].shift(1)

    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()

    return pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)


def calc_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average True Range (ATR) dengan Wilder Exponential Smoothing."""
    tr = calc_true_range(df)
    alpha = 1.0 / period
    return tr.ewm(alpha=alpha, min_periods=period, adjust=False).mean()


def calc_atr_sma(atr_series: pd.Series, period: int = 50) -> pd.Series:
    """SMA dari ATR (digunakan untuk baseline filter volatilitas)."""
    return atr_series.rolling(window=period, min_periods=period).mean()


# ─────────────────────────────────────────────────────────────
# 3. OSCILLATORS (RSI & ADX)
# ─────────────────────────────────────────────────────────────

def calc_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """Relative Strength Index (RSI) dengan Wilder Smoothing."""
    delta = series.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)

    alpha = 1.0 / period
    avg_gain = gain.ewm(alpha=alpha, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=alpha, min_periods=period, adjust=False).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100.0 - (100.0 / (1.0 + rs))


def calc_adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average Directional Index (ADX) standar Wilder."""
    high = df["high"]
    low = df["low"]
    prev_high = high.shift(1)
    prev_low = low.shift(1)

    up_move = high - prev_high
    down_move = prev_low - low

    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    tr = calc_true_range(df)
    alpha = 1.0 / period
    
    tr_smooth = tr.ewm(alpha=alpha, min_periods=period, adjust=False).mean()
    plus_di = 100 * pd.Series(plus_dm, index=df.index).ewm(alpha=alpha, min_periods=period, adjust=False).mean() / tr_smooth
    minus_di = 100 * pd.Series(minus_dm, index=df.index).ewm(alpha=alpha, min_periods=period, adjust=False).mean() / tr_smooth

    dx = 100 * (abs(plus_di - minus_di) / (plus_di + minus_di).replace(0, np.nan))
    return dx.ewm(alpha=alpha, min_periods=period, adjust=False).mean()


# ─────────────────────────────────────────────────────────────
# 4. HIGHER-TIMEFRAME (HTF) TREND
# ─────────────────────────────────────────────────────────────

def calc_htf_ema(
    df: pd.DataFrame,
    htf: str = "1h",
    period: int = 200,
) -> pd.Series:
    """
    Hitung EMA pada timeframe yang lebih tinggi (HTF, default 1H EMA 200) tanpa lookahead bias.
    Resample M5 ke bar HTF, hitung EMA, geser (shift 1) agar hanya memakai bar HTF
    yang sudah close, lalu map kembali ke bar M5 menggunakan pd.merge_asof.
    """
    htf_series = df.set_index("datetime")["close"].resample(htf).last().dropna()
    if len(htf_series) == 0:
        return pd.Series(index=df.index, dtype=float)

    htf_ema = htf_series.ewm(span=period, adjust=False).mean().shift(1)
    merged = pd.merge_asof(
        df[["datetime"]].sort_values("datetime"),
        htf_ema.rename("htf_ema").sort_index(),
        left_on="datetime",
        right_index=True,
    )
    return merged["htf_ema"]

"""
Asian Mean Reversion — Indicators Engine
==========================================
Kalkulasi kuantitatif: SMA, VWAP, Z-Score, RSI, ATR.
Semua fungsi bekerja pada pandas Series/DataFrame.
"""

import numpy as np
import pandas as pd

from configs import asia_config as cfg


# ═══════════════════════════════════════════════
#  1. NILAI TENGAH (MEAN / ANCHOR)
# ═══════════════════════════════════════════════

def calc_sma(series: pd.Series, period: int = cfg.ROLLING_WINDOW) -> pd.Series:
    """
    Simple Moving Average (SMA) rolling window.
    
    μ_t = (1/N) × Σ P_{t-i}  untuk i = 0..N-1
    """
    return series.rolling(window=period, min_periods=period).mean()


def calc_session_vwap(df: pd.DataFrame, session_labels: pd.Series) -> pd.Series:
    """
    Session VWAP — di-reset setiap awal sesi Asia (00:00 UTC).
    
    VWAP_t = Σ(P_i × V_i) / Σ(V_i)  sejak awal sesi.
    """
    typical_price = (df["high"] + df["low"] + df["close"]) / 3.0
    tp_vol = typical_price * df["volume"]

    cum_tp_vol = tp_vol.groupby(session_labels).cumsum()
    cum_vol = df["volume"].groupby(session_labels).cumsum()

    vwap = cum_tp_vol / cum_vol.replace(0, np.nan)
    return vwap


def calc_anchor(df: pd.DataFrame, session_labels: pd.Series = None) -> pd.Series:
    """
    Menghitung nilai tengah (anchor) — pilih VWAP atau SMA
    berdasarkan cfg.USE_VWAP.
    """
    if cfg.USE_VWAP and "volume" in df.columns and session_labels is not None:
        return calc_session_vwap(df, session_labels)
    return calc_sma(df["close"], cfg.ROLLING_WINDOW)


# ═══════════════════════════════════════════════
#  2. STANDAR DEVIASI (σ)
# ═══════════════════════════════════════════════

def calc_rolling_std(
    series: pd.Series,
    period: int = cfg.ROLLING_WINDOW,
    min_sigma: float = cfg.MIN_SIGMA,
) -> pd.Series:
    """
    Standar deviasi sampel rolling window dengan proteksi zero-division.
    
    σ_t = sqrt( (1/(N-1)) × Σ(P_{t-i} - μ_t)² )
    
    Jika σ_t < min_sigma → tetapkan σ_t = min_sigma.
    """
    std = series.rolling(window=period, min_periods=period).std(ddof=1)
    return std.clip(lower=min_sigma)


# ═══════════════════════════════════════════════
#  3. Z-SCORE
# ═══════════════════════════════════════════════

def calc_zscore(
    price: pd.Series,
    mean: pd.Series,
    std: pd.Series,
) -> pd.Series:
    """
    Z-Score menormalisasi deviasi harga dari nilai tengah.
    
    Z_t = (P_t - μ_t) / σ_t
    """
    return (price - mean) / std


# ═══════════════════════════════════════════════
#  4. RSI (Relative Strength Index — Wilder Smoothing)
# ═══════════════════════════════════════════════

def calc_rsi(series: pd.Series, period: int = cfg.RSI_PERIOD) -> pd.Series:
    """
    RSI dengan Wilder smoothing (Exponential Moving Average).
    
    RS = avg_gain / avg_loss
    RSI = 100 - (100 / (1 + RS))
    """
    delta = series.diff()

    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)

    # Wilder smoothing: EMA dengan alpha = 1/period
    alpha = 1.0 / period
    avg_gain = gain.ewm(alpha=alpha, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=alpha, min_periods=period, adjust=False).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100.0 - (100.0 / (1.0 + rs))

    return rsi


# ═══════════════════════════════════════════════
#  5. ATR (Average True Range — Wilder Smoothing)
# ═══════════════════════════════════════════════

def calc_true_range(df: pd.DataFrame) -> pd.Series:
    """
    True Range:
    TR_t = max(High - Low, |High - Close_{t-1}|, |Low - Close_{t-1}|)
    """
    high = df["high"]
    low = df["low"]
    prev_close = df["close"].shift(1)

    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()

    return pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)


def calc_atr(df: pd.DataFrame, period: int = cfg.ATR_PERIOD) -> pd.Series:
    """
    ATR dengan Wilder Smoothing:
    ATR_t = ((ATR_{t-1} × (period-1)) + TR_t) / period
    """
    tr = calc_true_range(df)

    # Wilder smoothing via EWM
    alpha = 1.0 / period
    atr = tr.ewm(alpha=alpha, min_periods=period, adjust=False).mean()
    return atr


def calc_atr_sma(
    atr_series: pd.Series,
    period: int = cfg.ATR_SMA_PERIOD,
) -> pd.Series:
    """
    SMA dari ATR — digunakan untuk gerbang atas volatilitas.
    """
    return atr_series.rolling(window=period, min_periods=period).mean()


# ═══════════════════════════════════════════════
#  ADX (Average Directional Index)
# ═══════════════════════════════════════════════

def calc_adx(df: pd.DataFrame, period: int = cfg.ADX_PERIOD) -> pd.Series:
    """Hitung ADX (Average Directional Index)."""
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
    plus_di = 100 * pd.Series(plus_dm, index=df.index).ewm(alpha=alpha, min_periods=period, adjust=False).mean() / tr.ewm(alpha=alpha, min_periods=period, adjust=False).mean()
    minus_di = 100 * pd.Series(minus_dm, index=df.index).ewm(alpha=alpha, min_periods=period, adjust=False).mean() / tr.ewm(alpha=alpha, min_periods=period, adjust=False).mean()

    dx = 100 * (abs(plus_di - minus_di) / (plus_di + minus_di).replace(0, np.nan))
    adx = dx.ewm(alpha=alpha, min_periods=period, adjust=False).mean()
    
    return adx


# ═══════════════════════════════════════════════
#  5. HIGHER-TIMEFRAME (HTF) TREND
# ═══════════════════════════════════════════════

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


# ═══════════════════════════════════════════════
#  6. COMPUTE ALL INDICATORS (PIPELINE)
# ═══════════════════════════════════════════════

def compute_all(df: pd.DataFrame) -> pd.DataFrame:
    """
    Hitung semua indikator dan tambahkan sebagai kolom baru ke DataFrame.
    """
    df = df.copy()

    # Pastikan datetime terurut
    df.sort_values("datetime", inplace=True)
    df.reset_index(drop=True, inplace=True)

    # Session labels (tanggal UTC) untuk VWAP reset
    session_labels = df["datetime"].dt.date if cfg.USE_VWAP else None

    # 1. Nilai tengah (anchor)
    df["anchor"] = calc_anchor(df, session_labels)

    # 2. Standar deviasi
    df["std"] = calc_rolling_std(df["close"], cfg.ROLLING_WINDOW, cfg.MIN_SIGMA)

    # 3. Z-Score
    df["zscore"] = calc_zscore(df["close"], df["anchor"], df["std"])

    # 4. RSI
    df["rsi"] = calc_rsi(df["close"], cfg.RSI_PERIOD)

    # 5. ATR
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

    # 8. Band (untuk visualisasi)
    df["upper_band"] = df["anchor"] + (cfg.Z_ENTRY_THRESHOLD * df["std"])
    df["lower_band"] = df["anchor"] - (cfg.Z_ENTRY_THRESHOLD * df["std"])

    return df

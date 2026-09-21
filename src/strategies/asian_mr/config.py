"""
Asian Mean Reversion Strategy — Configuration
===============================================
Parameter strategi mean-reversion sesi Asia XAU/USD (M5).
"""

# ─────────────────────────────────────────────
# SESSION TIMING (UTC)
# ─────────────────────────────────────────────
SESSION_ENTRY_START    = "01:00"     # Mulai cari sinyal
SESSION_ENTRY_END      = "04:30"     # Berhenti cari sinyal (hindari pre-London)
SESSION_HARD_CUTOFF    = "06:00"     # Tutup paksa semua posisi
SESSION_WARMUP_MINUTES = 0           # Start entry diubah ke 01:00
TIMEFRAME              = "M5"        # Timeframe candle

# ─────────────────────────────────────────────
# MEAN REVERSION ANCHOR
# ─────────────────────────────────────────────
ROLLING_WINDOW    = 20               # Jumlah bar untuk SMA & σ (N)
USE_VWAP          = False            # True = gunakan VWAP harian, False = gunakan SMA
SMA_PERIOD        = 20               # Periode rolling SMA
Z_ENTRY_THRESHOLD = 1.6              # Entry trigger (deviasi standar)
Z_EXIT_THRESHOLD  = 0.5              # TP: kembali ke rentang ekuilibrium [-0.5, 0.5]
Z_HARD_CUT        = 3.2              # Hard cut: stop loss darurat jika harga kabur ekstrim

# ─────────────────────────────────────────────
# OSCILLATORS & TREND FILTERS
# ─────────────────────────────────────────────
USE_RSI_FILTER    = False            # Bypass RSI filter jika False (andalkan Z-Score + Opposing Close)
RSI_PERIOD        = 14               # Periode RSI (Wilder smoothing)
RSI_OVERBOUGHT    = 65               # Level jenuh beli (dilonggarkan dari 70)
RSI_OVERSOLD      = 35               # Level jenuh jual (dilonggarkan dari 30)
ADX_PERIOD        = 14               # Periode ADX
ADX_MAX_THRESHOLD = 25               # Filter tren: maksimal ADX untuk mean reversion

# ─────────────────────────────────────────────
# HIGHER-TIMEFRAME (HTF) TREND FILTER
# ─────────────────────────────────────────────
USE_HTF_TREND_FILTER   = True        # True = aktifkan filter tren H1
HTF_TIMEFRAME          = "1h"        # Timeframe HTF untuk resampling
HTF_EMA_PERIOD         = 200         # Periode EMA pada timeframe HTF
HTF_FILTER_MODE        = "ASYMMETRIC_LONG_ONLY" # "SYMMETRIC" atau "ASYMMETRIC_LONG_ONLY"

# ─────────────────────────────────────────────
# ATR & VOLATILITY FILTER
# ─────────────────────────────────────────────
ATR_PERIOD             = 14          # Periode ATR (Wilder smoothing)
ATR_SL_MULTIPLIER      = 1.5         # Pengali ATR untuk stop loss
ATR_MIN_THRESHOLD      = 0.70        # Gerbang bawah: min ATR (USD)
ATR_ANOMALY_MULTIPLIER = 1.6         # Gerbang atas: pengali SMA(ATR)
ATR_SMA_PERIOD         = 50          # Periode SMA untuk rata-rata ATR

# ─────────────────────────────────────────────
# RISK MANAGEMENT
# ─────────────────────────────────────────────
MAX_TRADE_DURATION_MIN = 60          # Time stop: max 60 menit
MIN_SIGMA              = 0.0001      # Proteksi zero-division pada σ

# ─────────────────────────────────────────────
# CANDLE CONFIRMATION
# ─────────────────────────────────────────────
REQUIRE_OPPOSING_CLOSE = True        # Wajib candle penutupan berlawanan (Bearish untuk Short, Bullish untuk Long)

# ─────────────────────────────────────────────
# BACKTEST SETTINGS & POSITION SIZING
# ─────────────────────────────────────────────
INITIAL_CAPITAL        = 10_000.0    # Modal awal (USD)
USE_DYNAMIC_LOT        = True        # True = Fixed Dollar Risk, False = Static Lot
FIXED_RISK_USD         = 80.0        # Resiko maksimal per trade (USD) jika dynamic lot aktif
LOT_SIZE               = 0.1         # Ukuran lot statis (digunakan jika USE_DYNAMIC_LOT = False)
MIN_LOT                = 0.01        # Lot minimum
MAX_LOT                = 2.0         # Lot maksimum
LOT_STEP               = 0.01        # Kelipatan lot
POINT_VALUE            = 100.0       # Nilai per poin per lot (XAU/USD: $100/lot)
SPREAD_USD             = 0.30        # Estimasi spread dalam USD
COMMISSION_USD         = 0.0         # Komisi per side per lot (USD)
MAX_TRADES_PER_DAY     = 1           # Maksimal trade per hari untuk mencegah overtrading

# ─────────────────────────────────────────────
# DATA PATHS
# ─────────────────────────────────────────────
DATA_DIR          = "data"
SAMPLE_DATA_FILE  = "xauusd-m5-bid-2021-09-08-2026-09-08.csv"

"""
New York Opening Range Breakout (NY ORB) Strategy — Configuration
==================================================================
Parameter kuantitatif New York ORB:
1. Pembentukan Opening Range: 13:30 – 13:45 UTC (min 2 bar M5)
2. Jendela Eksekusi & Cutoff: 13:45 – 16:30 UTC
3. Filter Ekspansi: True Range (TR) candle sebelumnya > 1.5 x SMA(20) TR (100% Causal)
4. Risk / Reward: SL di batas seberang (1.0R = OR Range), TP di 2.0R
"""

# ─────────────────────────────────────────────
# 1. SESSION TIMING (UTC)
# ─────────────────────────────────────────────
ORB_START_TIME         = "13:30"     # Mulai Opening Range M15 (13:30 UTC)
ORB_END_TIME           = "13:45"     # Akhir Opening Range (13:45 UTC)
ENTRY_START_TIME       = "13:45"     # Mulai jendela eksekusi
ENTRY_END_TIME         = "16:30"     # Batas akhir eksekusi & cutoff posisi (16:30 UTC)
SESSION_HARD_CUTOFF    = "16:30"     # Tutup paksa posisi aktif jika belum TP/SL pada 16:30 UTC
TIMEFRAME              = "M5"
USE_DYNAMIC_DST        = True        # True = Dynamic DST via America/New_York (09:30 ET = 13:30 EDT / 14:30 EST)

# ─────────────────────────────────────────────
# 2. OPENING RANGE & EXPANSION FILTERS
# ─────────────────────────────────────────────
MIN_ORB_BARS           = 2           # Minimal 2 dari 3 bar M5 (13:30, 13:35, 13:40)
EXPANSION_MULT         = 1.5         # Pengali True Range candle sebelumnya (shift 1) terhadap SMA20 TR
EXPANSION_SMA_PERIOD   = 20          # Periode SMA untuk True Range
USE_EXPANSION_FILTER   = True        # True = Wajib Prior TR > 1.5 x SMA20 TR (100% Causal)

# ─────────────────────────────────────────────
# 3. RISK MANAGEMENT & EXIT PROTOCOL
# ─────────────────────────────────────────────
TARGET_RR              = 2.0         # Target Risk-to-Reward (TP = Entry +/- 2.0 * or_range)
SL_MODE                = "OPPOSITE"  # SL = Entry - or_range (Long), Entry + or_range (Short)
MAX_TRADES_PER_DAY     = 1           # Maksimal 1 trade per hari
ALLOW_REENTRY          = False       # False = 1 trade realistis per hari

# ─────────────────────────────────────────────
# 4. ACCOUNT, SIZING & BROKER FEES
# ─────────────────────────────────────────────
INITIAL_CAPITAL        = 10_000.0    # Modal awal (USD)
FIXED_RISK_USD         = 80.0        # Resiko dolar baseline ($80)
RISK_PER_TRADE_PCT     = 0.02        # 2.0% risiko per trade jika compounding aktif
MIN_LOT                = 0.01        # Lot minimum broker
MAX_LOT                = 10.0        # Lot maksimum
LOT_STEP               = 0.01        # Kelipatan lot
POINT_VALUE            = 100.0       # $100 per lot per $1 gerakan XAU/USD
SPREAD_USD             = 0.30        # Estimasi spread realistis broker ($0.30/oz XAU/USD)
COMMISSION_USD         = 0.0

# ─────────────────────────────────────────────
# 5. HIGHER-TIMEFRAME (HTF) TREND FILTER
# ─────────────────────────────────────────────
USE_HTF_TREND_FILTER   = False       # False = M5 murni tanpa filter HTF
HTF_TIMEFRAME          = "1h"        # Timeframe HTF
HTF_EMA_PERIOD         = 50          # Periode EMA pada timeframe HTF
HTF_FILTER_MODE        = "TREND_ALIGNED" # Long jika Close > HTF EMA, Short jika Close < HTF EMA

# ─────────────────────────────────────────────
# 6. DATA PATHS
# ─────────────────────────────────────────────
DATA_DIR               = "data"
SAMPLE_DATA_FILE       = "xauusd-m5-bid-2021-09-08-2026-09-08.csv"

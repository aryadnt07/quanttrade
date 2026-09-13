"""
London Pit Opening Range Breakout (London Pit ORB) — Configuration
===================================================================
Parameter kuantitatif London Pit ORB sesuai spesifikasi model mikrostruktur:
1. Pembentukan Opening Range: 08:00 – 08:15 UTC (min 2 bar M5, London Pit Open)
2. Jendela Eksekusi & Cutoff: 08:15 – 11:30 UTC
3. Filter Ekspansi: True Range (TR) candle > 1.8 x SMA(20) TR
4. Risk / Reward: SL di batas seberang (1.0R = LOR Range), TP di 2.0R
5. Entry Price: lor_high untuk Long, lor_low untuk Short (Stop Order)
6. Hard Cutoff: 11:30 UTC (Wajib flat sebelum New York pre-market)
"""

# ─────────────────────────────────────────────
# 1. SESSION TIMING (UTC)
# ─────────────────────────────────────────────
LORB_START_TIME        = "08:00"     # Mulai London Opening Range M15 (08:00 UTC)
LORB_END_TIME          = "08:15"     # Akhir London Opening Range (08:15 UTC)
ENTRY_START_TIME       = "08:15"     # Mulai jendela eksekusi sinyal
ENTRY_END_TIME         = "11:30"     # Batas akhir eksekusi & cutoff posisi (11:30 UTC)
SESSION_HARD_CUTOFF    = "11:30"     # Tutup paksa posisi aktif jika belum TP/SL pada 11:30 UTC
TIMEFRAME              = "M5"

# ─────────────────────────────────────────────
# 2. OPENING RANGE & EXPANSION FILTERS
# ─────────────────────────────────────────────
MIN_LORB_BARS          = 2           # Minimal 2 dari 3 bar M5 (08:00, 08:05, 08:10)
EXPANSION_MULT         = 1.5         # Pengali True Range candle sebelumnya (shift 1) terhadap SMA20 TR
EXPANSION_SMA_PERIOD   = 20          # Periode SMA untuk True Range
USE_EXPANSION_FILTER   = True        # True = Wajib Prior TR > 1.5 x SMA20 TR (100% Causal)

# ─────────────────────────────────────────────
# 3. RISK MANAGEMENT & EXIT PROTOCOL
# ─────────────────────────────────────────────
TARGET_RR              = 2.0         # Target Risk-to-Reward (TP = Entry +/- 2.0 * lor_range)
SL_MODE                = "OPPOSITE"  # SL = Entry - lor_range (Long), Entry + lor_range (Short)
MAX_TRADES_PER_DAY     = 1           # Maksimal 1 trade per hari
ALLOW_REENTRY          = False       # False = 1 trade realistis per hari

# ─────────────────────────────────────────────
# 4. ACCOUNT, SIZING & BROKER FEES
# ─────────────────────────────────────────────
INITIAL_CAPITAL        = 10_000.0    # Modal awal (USD)
FIXED_RISK_USD         = 80.0        # Resiko dolar baseline ($80)
RISK_PER_TRADE_PCT     = 0.02        # 2.0% risiko per trade dalam portofolio
MIN_LOT                = 0.01        # Lot minimum broker
MAX_LOT                = 10.0        # Lot maksimum
LOT_STEP               = 0.01        # Kelipatan lot
POINT_VALUE            = 100.0       # $100 per lot per $1 gerakan XAU/USD
SPREAD_USD             = 0.30        # Estimasi spread realistis broker ($0.30/oz)
COMMISSION_USD         = 0.0

# ─────────────────────────────────────────────
# 5. HIGHER-TIMEFRAME (HTF) TREND FILTER
# ─────────────────────────────────────────────
USE_HTF_TREND_FILTER   = False       # False = M5 murni (PF 2.53), True = Filter H1 EMA50 (PF 3.09)
HTF_TIMEFRAME          = "1h"        # Timeframe HTF
HTF_EMA_PERIOD         = 50          # Periode EMA pada timeframe HTF
HTF_FILTER_MODE        = "TREND_ALIGNED" # Long jika Close > HTF EMA, Short jika Close < HTF EMA

# ─────────────────────────────────────────────
# 6. DATA PATHS
# ─────────────────────────────────────────────
DATA_DIR               = "data"
SAMPLE_DATA_FILE       = "xauusd-m5-bid-2021-09-08-2026-09-08.csv"

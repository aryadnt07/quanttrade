"""
New York Opening Range Breakout (NY ORB) Strategy — Configuration
==================================================================
Parameter kuantitatif New York ORB sesuai spesifikasi model:
1. Pembentukan Opening Range: 13:30 – 13:45 UTC (min 2 bar M5)
2. Jendela Eksekusi & Cutoff: 13:45 – 16:30 UTC
3. Filter Ekspansi: True Range (TR) candle > 1.8 x SMA(20) TR
4. Risk / Reward: SL di batas seberang (1.0R = OR Range), TP di 2.0R
5. Entry Price: or_high untuk Long, or_low untuk Short
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

# ─────────────────────────────────────────────
# 2. OPENING RANGE & EXPANSION FILTERS
# ─────────────────────────────────────────────
MIN_ORB_BARS           = 2           # Minimal 2 dari 3 bar M5 (13:30, 13:35, 13:40)
EXPANSION_MULT         = 1.8         # Pengali True Range terhadap SMA20 TR
EXPANSION_SMA_PERIOD   = 20          # Periode SMA untuk True Range
USE_EXPANSION_FILTER   = True        # True = Wajib TR > 1.8 x SMA20 TR

# ─────────────────────────────────────────────
# 3. RISK MANAGEMENT & EXIT PROTOCOL
# ─────────────────────────────────────────────
TARGET_RR              = 2.0         # Target Risk-to-Reward (TP = Entry +/- 2.0 * or_range)
SL_MODE                = "OPPOSITE"  # SL = Entry - or_range (Long), Entry + or_range (Short)
MAX_TRADES_PER_DAY     = 1           # Maksimal 1 trade per hari (menghindari phantom re-entry)
ALLOW_REENTRY          = False       # False = 1 trade realistis per hari, True = Izinkan re-entry jika setup terpenuhi

# ─────────────────────────────────────────────
# 4. ACCOUNT, SIZING & BROKER FEES
# ─────────────────────────────────────────────
INITIAL_CAPITAL        = 10_000.0    # Modal awal (USD)
FIXED_RISK_USD         = 80.0        # Resiko dolar baseline ($80)
RISK_PER_TRADE_PCT     = 0.01        # 1.0% risiko per trade jika compounding aktif
MIN_LOT                = 0.01        # Lot minimum broker
MAX_LOT                = 10.0        # Lot maksimum
LOT_STEP               = 0.01        # Kelipatan lot
POINT_VALUE            = 100.0       # $100 per lot per $1 gerakan XAU/USD
SPREAD_USD             = 0.0         # Spread sesuai model R murni (atau 0.30 jika dihitung biaya)
COMMISSION_USD         = 0.0

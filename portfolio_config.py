"""
Master Multi-Regime Portfolio — Configuration File
==================================================
Parameter global untuk portofolio kuantitatif XAU/USD:
1. Asian Mean Reversion (M5) — Sesi Asia (01:00 - 04:30 UTC)
2. New York Opening Range Breakout (M5) — Sesi New York (13:45 - 16:30 UTC)

Beroperasi pada satu akun modal tunggal ($10,000)
dengan kontrol risiko asimetris & perlindungan de-risking dinamis.
"""

import config as asian_cfg
import ny_config as ny_cfg
import london_config as london_cfg

# ─────────────────────────────────────────────
# 1. PORTFOLIO ACCOUNT & CAPITAL
# ─────────────────────────────────────────────
PORTFOLIO_NAME            = "XAU/USD Quantitative Master Portfolio (Asia MR + London ORB + NY ORB)"
PORTFOLIO_INITIAL_CAPITAL = 10_000.0   # Modal awal gabungan (USD)
ANNUAL_TRADING_DAYS       = 252        # Standar hari trading per tahun (kalkulasi Sharpe)

# ─────────────────────────────────────────────
# 2. STRATEGY SWITCHES & ASYMMETRIC ALLOCATION
# ─────────────────────────────────────────────
ENABLE_ASIAN_MR           = True       # Aktifkan strategi Asian Mean Reversion
ENABLE_STRATEGY_2         = True       # Aktifkan New York Opening Range Breakout
STRATEGY_2_NAME           = "NY_ORB"
ENABLE_LONDON_ORB         = True       # Aktifkan London Pit Opening Range Breakout
STRATEGY_3_NAME           = "LONDON_ORB"

# Baseline dollar risk untuk normalisasi lot
ASIAN_FIXED_RISK_USD      = 80.0       # Resiko baseline modul Asia ($80)
NY_FIXED_RISK_USD         = 80.0       # Resiko baseline modul New York ($80)
LONDON_FIXED_RISK_USD     = 80.0       # Resiko baseline modul London ($80)

# ─────────────────────────────────────────────
# 3. DYNAMIC COMPOUNDING & ASYMMETRIC RISK SHIFTING
# ─────────────────────────────────────────────
USE_COMPOUNDING           = True       # True = Aktifkan compounding pertumbuhan modal
ASIAN_RISK_PCT            = 0.01       # 1.0% per trade (Asia Mean Reversion)
LONDON_RISK_PCT           = 0.02       # 2.0% per trade (London Pit ORB)
NY_RISK_PCT               = 0.02       # 2.0% per trade (New York Opening Range Breakout)

MIN_LOT                   = 0.01       # Lot minimum broker
MAX_LOT                   = 10.0       # Lot maksimum broker (menampung pertumbuhan akun 50k+)
LOT_STEP                  = 0.01       # Kelipatan lot

# ─────────────────────────────────────────────
# 4. CAPITAL PROTECTION (DYNAMIC DE-RISKING)
# ─────────────────────────────────────────────
# Dynamic De-Risking Cooldown:
# Jika akun mengalami 2 hari rugi berturut-turut, pangkas risiko entri sebesar 50%.
# Begitu sistem mencetak profit / TP, risiko kembali normal.
ENABLE_DYNAMIC_DERISKING   = True   # True = Pangkas risiko saat loss streak
DERISKING_CONSECUTIVE_DAYS = 2      # Ambang batas hari rugi berturut-turut (2 hari)
DERISKING_RATIO            = 0.5    # Pangkas 50% risiko saat cooldown

# ─────────────────────────────────────────────
# 5. TIMING REFERENCE
# ─────────────────────────────────────────────
ASIAN_ENTRY_WINDOW        = f"{asian_cfg.SESSION_ENTRY_START} – {asian_cfg.SESSION_ENTRY_END} UTC"
LONDON_ENTRY_WINDOW       = f"{london_cfg.ENTRY_START_TIME} – {london_cfg.ENTRY_END_TIME} UTC"
NY_ENTRY_WINDOW           = f"{ny_cfg.ENTRY_START_TIME} – {ny_cfg.ENTRY_END_TIME} UTC"

# ─────────────────────────────────────────────
# 6. MULTI-TIMEFRAME DATA PATHS (5-YEAR DEFAULT)
# ─────────────────────────────────────────────
DEFAULT_DATA_M1           = "data/xauusd-m1-bid-2021-09-08-2026-09-08.csv"
DEFAULT_DATA_M5           = "data/xauusd-m5-bid-2021-09-08-2026-09-08.csv"
DEFAULT_DATA_H1           = "data/xauusd-h1-bid-2021-09-08-2026-09-08.csv"
DEFAULT_DATA_H4           = "data/xauusd-h4-bid-2021-09-08-2026-09-08.csv"
DEFAULT_DATA_M15          = "data/xauusd-m15-bid-2021-09-08-2026-09-08.csv"

# Bar Magnifier Execution (M1 Intrabar Resolution)
USE_M1_EXECUTION          = True       # True = Eksekusi presisi 1-menit (Bar Magnifier)



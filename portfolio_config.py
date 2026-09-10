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

# ─────────────────────────────────────────────
# 1. PORTFOLIO ACCOUNT & CAPITAL
# ─────────────────────────────────────────────
PORTFOLIO_NAME            = "XAU/USD Quantitative Master Portfolio (Asia MR + NY ORB)"
PORTFOLIO_INITIAL_CAPITAL = 10_000.0   # Modal awal gabungan (USD)
ANNUAL_TRADING_DAYS       = 252        # Standar hari trading per tahun (kalkulasi Sharpe)

# ─────────────────────────────────────────────
# 2. STRATEGY SWITCHES & ASYMMETRIC ALLOCATION
# ─────────────────────────────────────────────
ENABLE_ASIAN_MR           = True       # Aktifkan strategi Asian Mean Reversion
ENABLE_STRATEGY_2         = True       # Aktifkan New York Opening Range Breakout
STRATEGY_2_NAME           = "NY_ORB"

# Baseline dollar risk untuk normalisasi lot
ASIAN_FIXED_RISK_USD      = 80.0       # Resiko baseline modul Asia ($80)
NY_FIXED_RISK_USD         = 80.0       # Resiko baseline modul New York ($80)

# ─────────────────────────────────────────────
# 3. DYNAMIC COMPOUNDING & ASYMMETRIC RISK SHIFTING
# ─────────────────────────────────────────────
USE_COMPOUNDING           = True       # True = Aktifkan compounding pertumbuhan modal
ASIAN_RISK_PCT            = 0.02       # 2.0% per trade (Cash Cow utama)
NY_RISK_PCT               = 0.01       # 1.0% per trade (Pemanen momentum asimetris)

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
NY_ENTRY_WINDOW           = f"{ny_cfg.ENTRY_START_TIME} – {ny_cfg.ENTRY_END_TIME} UTC"

"""
Live Trading Configuration — Multi-Regime Master Portfolio (MT5)
================================================================
Konfigurasi koneksi real-time, manajemen risiko live, dan parameter eksekusi
untuk 3 modul kuantitatif:
1. Asian Mean Reversion (01:00 - 04:30 UTC)
2. London Pit Opening Range Breakout (08:15 - 11:30 UTC)
3. New York Opening Range Breakout (09:45 - 12:30 NY Local / Dynamic UTC DST)

Fitur Keamanan Institusional:
- Anti-Chasing Ceiling (Mencegah beli di pucuk saat lonjakan harga)
- Requote / Spam Lockout Guard (Maksimal 3 retry, anti-banned broker)
- Dynamic DST Tracking (Auto-convert jam buka Wall Street EST/EDT ke UTC)
- Low-Latency Polling (100ms pada jendela breakout)
- Dukungan Dual Execution Mode (Fast-Tick IOC vs Pending Stop OCO)
"""

# ─────────────────────────────────────────────
# 1. KREDENSIAL AKUN BROKER MT5 (EXNESS / ECN)
# ─────────────────────────────────────────────
ACCOUNT_LOGIN           = 434215986                # Nomor Akun MT5
ACCOUNT_SERVER          = "Exness-MT5Trial7"       # Server Broker MT5
SYMBOL                  = "XAUUSD"                 # Simbol Gold di MT5
MAGIC_NUMBER            = 888001                   # ID Unik Order Bot
SLIPPAGE_POINTS         = 30                       # Toleransi slippage broker (points)

# ─────────────────────────────────────────────
# 2. MANAJEMEN RISIKO LIVE & ASYMMETRIC SIZING
# ─────────────────────────────────────────────
ASIAN_RISK_PCT          = 0.01                     # 1.0% risiko per trade untuk sesi Asia
LONDON_RISK_PCT         = 0.02                     # 2.0% risiko per trade untuk sesi London
NY_RISK_PCT             = 0.02                     # 2.0% risiko per trade untuk sesi New York

MIN_LOT                 = 0.01                     # Lot minimum broker
MAX_LOT                 = 5.00                     # Batas atas lot pengaman live (anti over-leverage)
LOT_STEP                = 0.01                     # Kelipatan lot broker
POINT_VALUE             = 100.0                    # $100 per lot per $1 gerakan XAU/USD

# ─────────────────────────────────────────────
# 3. SAFETY GUARDS & PROTEKSI PASAR (AUDIT FIX)
# ─────────────────────────────────────────────
MAX_SPREAD_USD          = 0.60                     # Batas spread maksimal (USD)
MAX_OPEN_TRADES         = 1                        # Maksimal 1 posisi aktif simultan (zero overlap)
DRY_RUN                 = False                    # True = Simulasi sinyal tanpa kirim order riil; False = Live Order

# Anti-Spam / Max-Retries Guard (Point #2 Audit)
MAX_SESSION_RETRIES     = 3                        # Maksimal percobaan order jika ditolak broker sebelum lockout
RETRY_COOLDOWN_SEC      = 3.0                      # Jeda waktu antar retry jika terjadi penolakan broker (detik)

# Anti-Chasing Guard (Point #1 & #3 Audit)
MAX_CHASE_USD           = 0.80                     # Toleransi mengejar harga breakout ($0.80 / 8 pips - fleksibel untuk emas)
POLL_INTERVAL_FAST_SEC  = 0.1                      # Polling rate saat jendela breakout aktif (100ms - responsif)
POLL_INTERVAL_IDLE_SEC  = 1.0                      # Polling rate saat di luar jendela breakout (1.0s - hemat CPU)

# ─────────────────────────────────────────────
# 4. EXECUTION ROUTING MODE (Point #1 Audit)
# ─────────────────────────────────────────────
# "FAST_TICK_IOC"    : Market order 100ms dengan filter ekspansi TR > 1.8x & anti-chasing guard (Rekomendasi Edge)
# "PENDING_STOP_OCO" : Pending Buy Stop & Sell Stop langsung ditanam di server MT5 saat OR terbentuk
BREAKOUT_EXECUTION_MODE = "FAST_TICK_IOC"

# ─────────────────────────────────────────────
# 5. DAYLIGHT SAVING TIME (DST) TRACKING (Point #4 Audit)
# ─────────────────────────────────────────────
USE_DYNAMIC_DST         = True                     # True = Otomatis hitung jam buka Wall Street 09:30 AM America/New_York
USE_LONDON_LOCAL_TIME   = False                    # True = 08:00 BST/GMT, False = 08:00 UTC konsisten

# ─────────────────────────────────────────────
# 6. STRATEGY SWITCHES
# ─────────────────────────────────────────────
ENABLE_ASIAN_MR         = True                     # Jalankan Asian Mean Reversion
ENABLE_LONDON_ORB       = True                     # Jalankan London Pit ORB
ENABLE_NY_ORB           = True                     # Jalankan New York ORB

# ─────────────────────────────────────────────
# 7. PARAMETER DEFAULT SESI (UTC STANDAR)
# ─────────────────────────────────────────────
# Modul 1: Asian Mean Reversion (Tokyo/Singapura tidak ada DST)
ASIAN_START_TIME        = (1, 0)                   # 01:00 UTC
ASIAN_END_TIME          = (4, 30)                  # 04:30 UTC
ASIAN_CUTOFF_TIME       = (6, 0)                   # 06:00 UTC (Hard Cutoff)

# Modul 2: London Pit ORB
LONDON_OR_START         = (8, 0)                   # 08:00 UTC
LONDON_OR_END           = (8, 15)                  # 08:15 UTC (Pembentukan Box Opening Range)
LONDON_ENTRY_START      = (8, 15)                  # 08:15 UTC
LONDON_ENTRY_END        = (11, 30)                 # 11:30 UTC
LONDON_CUTOFF_TIME      = (11, 25)                 # 11:25 UTC (Sesi berakhir, tutup posisi jika floating)
LONDON_TARGET_RR        = 2.0                      # Target Reward:Risk 2.0R
LONDON_EXPANSION        = 1.5                      # Syarat Prior TR ekspansi > 1.5x SMA20 (100% Kausal)

# Modul 3: New York ORB (Fallback jika USE_DYNAMIC_DST = False)
NY_OR_START             = (13, 30)                 # 13:30 UTC
NY_OR_END               = (13, 45)                 # 13:45 UTC (Pembentukan Box Opening Range)
NY_ENTRY_START          = (13, 45)                 # 13:45 UTC
NY_ENTRY_END            = (16, 30)                 # 16:30 UTC
NY_CUTOFF_TIME          = (16, 25)                 # 16:25 UTC (Sesi berakhir, tutup posisi jika floating)
NY_TARGET_RR            = 2.0                      # Target Reward:Risk 2.0R (sesuai ny_config.py)
NY_EXPANSION            = 1.5                      # Syarat Prior TR ekspansi > 1.5x SMA20 (100% Kausal)

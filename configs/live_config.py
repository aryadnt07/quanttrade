"""
Live Trading Configuration — Multi-Regime Master Portfolio (MT5)
================================================================
Konfigurasi koneksi real-time, manajemen risiko live, dan parameter eksekusi
untuk 3 modul kuantitatif:
1. Asian Mean Reversion (01:00 - 04:30 UTC)
2. London Pit Opening Range Breakout (08:15 - 11:30 UTC)
3. New York Opening Range Breakout (09:45 - 12:30 NY Local / Dynamic UTC DST)
"""

import os
from pathlib import Path

# ─────────────────────────────────────────────
# 0. LOAD ENVIRONMENT VARIABLES (.env)
# ─────────────────────────────────────────────
_env_loaded = False
try:
    from dotenv import load_dotenv
    _env_path = Path(__file__).resolve().parent.parent / ".env"
    if _env_path.exists():
        load_dotenv(dotenv_path=_env_path, override=False)
        _env_loaded = True
except ImportError:
    pass

if not _env_loaded:
    _env_path = Path(__file__).resolve().parent.parent / ".env"
    if _env_path.exists():
        try:
            with open(_env_path, "r", encoding="utf-8") as _f:
                for _line in _f:
                    _line = _line.strip()
                    if _line and not _line.startswith("#") and "=" in _line:
                        _k, _v = _line.split("=", 1)
                        os.environ.setdefault(_k.strip(), _v.strip().strip("'\""))
        except Exception:
            pass

def _get_env_bool(key: str, default: bool) -> bool:
    val = os.getenv(key)
    if val is None or not val.strip():
        return default
    return val.strip().lower() in ("true", "1", "yes", "on")

def _get_env_int(key: str, default: int) -> int:
    val = os.getenv(key)
    if val is None or not val.strip():
        return default
    try:
        return int(val.strip())
    except ValueError:
        return default

def _get_env_str(key: str, default: str) -> str:
    val = os.getenv(key)
    if val is None or not val.strip():
        return default
    return val.strip()

# ─────────────────────────────────────────────
# 1. KREDENSIAL AKUN BROKER MT5 (EXNESS / ECN)
# ─────────────────────────────────────────────
ACCOUNT_LOGIN           = _get_env_int("MT5_ACCOUNT_LOGIN", 434215986)
ACCOUNT_PASSWORD        = _get_env_str("MT5_ACCOUNT_PASSWORD", "")
ACCOUNT_SERVER          = _get_env_str("MT5_ACCOUNT_SERVER", "Exness-MT5Trial7")
SYMBOL                  = _get_env_str("MT5_SYMBOL", "XAUUSD")
MAGIC_NUMBER            = _get_env_int("MT5_MAGIC_NUMBER", 888001)
SLIPPAGE_POINTS         = _get_env_int("MT5_SLIPPAGE_POINTS", 30)

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
# 3. SAFETY GUARDS & PROTEKSI PASAR
# ─────────────────────────────────────────────
MAX_SPREAD_USD          = 0.60                     # Batas spread maksimal (USD)
MAX_OPEN_TRADES         = 1                        # Maksimal 1 posisi aktif simultan (zero overlap)
DRY_RUN                 = _get_env_bool("DRY_RUN", False)

# Anti-Spam / Max-Retries Guard
MAX_SESSION_RETRIES     = 3                        # Maksimal percobaan order jika ditolak broker sebelum lockout
RETRY_COOLDOWN_SEC      = 3.0                      # Jeda waktu antar retry jika terjadi penolakan broker (detik)

# Anti-Chasing Guard
MAX_CHASE_USD           = 0.80                     # Toleransi mengejar harga breakout ($0.80 / 8 pips)
POLL_INTERVAL_FAST_SEC  = 0.1                      # Polling rate saat jendela breakout aktif (100ms)
POLL_INTERVAL_IDLE_SEC  = 1.0                      # Polling rate saat di luar jendela breakout (1.0s)

# ─────────────────────────────────────────────
# 4. EXECUTION ROUTING MODE
# ─────────────────────────────────────────────
BREAKOUT_EXECUTION_MODE = "FAST_TICK_IOC"

# ─────────────────────────────────────────────
# 5. DAYLIGHT SAVING TIME (DST) TRACKING
# ─────────────────────────────────────────────
USE_DYNAMIC_DST         = True                     # True = Otomatis hitung jam buka Wall Street
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
# Modul 1: Asian Mean Reversion
ASIAN_START_TIME        = (1, 0)                   # 01:00 UTC
ASIAN_END_TIME          = (4, 30)                  # 04:30 UTC
ASIAN_CUTOFF_TIME       = (6, 0)                   # 06:00 UTC (Hard Cutoff)

# Modul 2: London Pit ORB
LONDON_OR_START         = (8, 0)                   # 08:00 UTC
LONDON_OR_END           = (8, 15)                  # 08:15 UTC (Pembentukan Box Opening Range)
LONDON_ENTRY_START      = (8, 15)                  # 08:15 UTC
LONDON_ENTRY_END        = (11, 30)                 # 11:30 UTC
LONDON_CUTOFF_TIME      = (11, 25)                 # 11:25 UTC
LONDON_TARGET_RR        = 2.0                      # Target Reward:Risk 2.0R
LONDON_EXPANSION        = 1.5                      # Syarat Prior TR ekspansi > 1.5x SMA20

# Modul 3: New York ORB
NY_OR_START             = (13, 30)                 # 13:30 UTC
NY_OR_END               = (13, 45)                 # 13:45 UTC (Pembentukan Box Opening Range)
NY_ENTRY_START          = (13, 45)                 # 13:45 UTC
NY_ENTRY_END            = (16, 30)                 # 16:30 UTC
NY_CUTOFF_TIME          = (16, 25)                 # 16:25 UTC
NY_EXPANSION            = 1.5                      # Syarat Prior TR ekspansi > 1.5x SMA20

# ─────────────────────────────────────────────
# 8. TELEGRAM NOTIFICATIONS (OPTION A: BALANCED MODE)
# ─────────────────────────────────────────────
TELEGRAM_ENABLED        = _get_env_bool("TELEGRAM_ENABLED", False)
TELEGRAM_BOT_TOKEN      = _get_env_str("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID        = _get_env_str("TELEGRAM_CHAT_ID", "")
TELEGRAM_NOTIFY_MODE    = _get_env_str("TELEGRAM_NOTIFY_MODE", "BALANCED")
TELEGRAM_HEARTBEAT_UTC_HOUR = _get_env_int("TELEGRAM_HEARTBEAT_UTC_HOUR", 0)



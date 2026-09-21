"""
Core Domain Types & Data Contracts
==================================
Stateless enums and dataclasses representing trading actions, orders, signals,
and performance attribution across backtest and live execution.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional
import pandas as pd


class Direction(str, Enum):
    """Arah posisi trading standar."""
    LONG = "LONG"
    SHORT = "SHORT"
    BUY = "BUY"
    SELL = "SELL"

    @property
    def is_long(self) -> bool:
        return self in (Direction.LONG, Direction.BUY)

    @property
    def is_short(self) -> bool:
        return self in (Direction.SHORT, Direction.SELL)


class ExitReason(str, Enum):
    """Penyebab penutupan posisi standar institusional."""
    # Breakout Exits
    TP = "TP"
    SL = "SL"
    TIME = "TIME"

    # Asian Mean Reversion Exits
    TAKE_PROFIT = "TP_Z_NEUTRAL"       # Z kembali ke area ekuilibrium
    STOP_LOSS = "SL_ATR"             # Harga menyentuh SL ATR
    HARD_CUT = "HARD_CUT_Z"           # |Z| > 3.2
    TIME_STOP = "TIME_STOP_60M"         # Durasi > 60 menit
    SESSION_CUTOFF = "SESSION_CUTOFF"   # Batas akhir sesi bursa

    # Aliases
    TP_Z_NEUTRAL = "TP_Z_NEUTRAL"
    TAKE_PROFIT_Z = "TP_Z_NEUTRAL"
    SL_ATR = "SL_ATR"
    STOP_LOSS_ATR = "SL_ATR"
    HARD_CUT_Z = "HARD_CUT_Z"
    TIME_STOP_60M = "TIME_STOP_60M"


@dataclass
class Signal:
    """Representasi satu sinyal trading kuantitatif."""
    bar_index: int
    datetime: pd.Timestamp
    direction: Direction
    entry_price: float
    stop_loss: float
    take_profit: Optional[float]
    zscore: float = 0.0
    rsi: float = 50.0
    atr: float = 0.0
    lot_size: float = 0.1
    initial_risk: float = 0.0


@dataclass
class TradeResult:
    """Hasil akhir eksekusi satu trade (setelah exit)."""
    entry_signal: Signal
    exit_index: int
    exit_datetime: pd.Timestamp
    exit_price: float
    exit_reason: ExitReason
    pnl_points: float           # Profit/loss dalam poin harga
    pnl_usd: float              # Profit/loss dalam USD
    duration_minutes: float     # Durasi trade dalam menit
    lot_size: float = 0.1       # Ukuran lot yang dieksekusi
    mfe_usd: float = 0.0        # Maximum Favorable Excursion
    mae_usd: float = 0.0        # Maximum Adverse Excursion


@dataclass
class PortfolioTradeRecord:
    """Struktur data standar trade gabungan portofolio multi-sesi."""
    strategy: str                     # "ASIAN_MR", "LONDON_ORB", atau "NY_ORB"
    entry_datetime: pd.Timestamp
    exit_datetime: pd.Timestamp
    direction: str                    # "LONG" / "BUY" / "SHORT" / "SELL"
    lot_size: float
    entry_price: float
    exit_price: float
    pnl_usd: float
    pnl_points: float
    exit_reason: str
    duration_minutes: float
    mfe_usd: float = 0.0
    mae_usd: float = 0.0


@dataclass
class AccountStatus:
    """Snapshot status akun broker."""
    login: int
    server: str
    balance: float
    equity: float
    margin: float
    free_margin: float
    currency: str
    trade_allowed: bool = True


@dataclass
class OrderResult:
    """Hasil respon eksekusi order dari broker."""
    success: bool
    retcode: int
    order_id: int
    price: float
    volume: float
    comment: str


@dataclass
class OrderIntent:
    """
    Niat/Instruksi order dari Domain Strategy ke Execution Layer.
    Murni membawa intensi trading tanpa terikat pada spesifik broker.
    """
    strategy_id: str                      # "ASIAN", "LONDON", "NY"
    action: str                           # "BUY", "SELL", "BUY_STOP", "SELL_STOP"
    volume: float                         # Lot size
    entry_price: float                    # Target entry / stop price
    stop_loss: float                      # Stop loss price
    take_profit: Optional[float]          # Take profit price (None jika dynamic)
    comment: str                          # Order comment tag
    magic_number: int = 888001            # Unique EA identifier
    metadata: Optional[dict] = None       # Parameter tambahan (spread, atr, zscore, dll)


@dataclass
class ExitIntent:
    """
    Niat/Instruksi penutupan posisi dari Domain Strategy ke Execution Layer.
    """
    ticket: int                           # Broker position ticket ID
    should_exit: bool                     # True jika posisi harus ditutup
    reason: str                           # Deskripsi alasan exit (misal: "Z-Neutral Mean Reversion")
    comment: str                          # Komentar singkat untuk broker deal (misal: "TP-Z-Neutral")
    strategy_id: str = ""                 # "ASIAN", "LONDON", "NY"

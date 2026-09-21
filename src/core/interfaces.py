"""
Core Architecture Interfaces & Protocols (Ports & Adapters)
===========================================================
Definisi protokol standar yang memisahkan Domain Strategi dari
Infrastruktur Eksekusi Broker (MT5, Paper Broker, Backtester).
"""

from typing import Protocol, runtime_checkable, Optional, List, Any, Dict
import pandas as pd
from datetime import datetime

from src.core.types import (
    OrderIntent,
    ExitIntent,
    OrderResult,
    AccountStatus,
)


@runtime_checkable
class IBroker(Protocol):
    """
    Port Antarmuka Broker Adapter.
    Memungkinkan Execution Runner berkomunikasi dengan broker manapun
    (MT5, FIX API, cTrader, Paper Simulator, MockBroker) secara seragam.
    """

    def connect(self) -> bool:
        """Koneksi ke terminal broker."""
        ...

    def get_account_status(self) -> Optional[AccountStatus]:
        """Ambil snapshot saldo, ekuitas, dan margin."""
        ...

    def get_current_tick(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Ambil tick harga real-time (bid, ask, spread, time)."""
        ...

    def get_recent_candles(self, symbol: str, timeframe: int, count: int) -> Optional[pd.DataFrame]:
        """Ambil data candle historis terkini."""
        ...

    def open_market_order(
        self,
        direction: str,
        volume: float,
        sl: float,
        tp: Optional[float] = None,
        comment: str = "",
        symbol: Optional[str] = None,
        magic: Optional[int] = None,
    ) -> OrderResult:
        """Eksekusi order pasar langsung (BUY/SELL)."""
        ...

    def place_pending_order(
        self,
        order_type: str,
        volume: float,
        price: float,
        sl: float,
        tp: Optional[float] = None,
        comment: str = "",
        symbol: Optional[str] = None,
        magic: Optional[int] = None,
    ) -> OrderResult:
        """Pasang pending stop order (BUY_STOP/SELL_STOP)."""
        ...

    def close_position(self, ticket: int, comment: str = "") -> OrderResult:
        """Tutup posisi trading aktif berdasarkan ticket."""
        ...

    def cancel_pending_order(self, ticket: int) -> OrderResult:
        """Batalkan pending order yang belum terisi."""
        ...

    def get_open_positions(self, symbol: Optional[str] = None) -> List[Any]:
        """Dapatkan seluruh posisi aktif."""
        ...

    def get_open_orders(self, symbol: Optional[str] = None) -> List[Any]:
        """Dapatkan seluruh pending orders aktif."""
        ...

    def get_broker_server_utc_offset_seconds(self) -> int:
        """Dapatkan offset waktu broker dalam detik terhadap UTC."""
        ...


@runtime_checkable
class IStrategy(Protocol):
    """
    Port Antarmuka Quantitative Strategy Domain.
    Murni bertugas memproses data pasar dan menghasilkan instruksi (Intents),
    tanpa mengetahui keberadaan MT5, OS, file sistem, atau Telegram.
    """

    @property
    def strategy_id(self) -> str:
        """Identitas unik strategi ('ASIAN', 'LONDON', 'NY')."""
        ...

    def evaluate_entry(
        self,
        df_m5: pd.DataFrame,
        tick: Dict[str, Any],
        equity: float,
        now_utc: datetime,
    ) -> Optional[OrderIntent]:
        """Evaluasi data pasar dan kembalikan OrderIntent jika kondisi entry terpenuhi."""
        ...

    def evaluate_exit(
        self,
        position: Any,
        df_m5: pd.DataFrame,
        now_utc: datetime,
        broker_utc_offset_sec: int = 0,
    ) -> Optional[ExitIntent]:
        """Evaluasi posisi aktif dan kembalikan ExitIntent jika kondisi keluar terpenuhi."""
        ...


@runtime_checkable
class ILiveStrategy(Protocol):
    """
    Port Antarmuka Live Execution Strategy (Composite Strategy).
    Menggabungkan evaluasi domain dengan manajemen state sesi trading live
    (tracking status order, retry count, OCO cancellation, dan lifecycle harian).
    """

    @property
    def strategy_id(self) -> str:
        """Identitas unik strategi ('ASIAN', 'LONDON', 'NY')."""
        ...

    @property
    def name(self) -> str:
        """Nama human-readable strategi ('Asia MR', 'London Pit ORB', dll)."""
        ...

    @property
    def trades_today(self) -> bool:
        """Status apakah strategi sudah mengeksekusi trade hari ini."""
        ...

    @trades_today.setter
    def trades_today(self, value: bool) -> None:
        ...

    @property
    def order_in_flight(self) -> bool:
        """Mutex in-flight order status."""
        ...

    @order_in_flight.setter
    def order_in_flight(self, value: bool) -> None:
        ...

    def can_trade(self) -> bool:
        """Cek apakah strategi siap dan diizinkan mengambil trade baru."""
        ...

    def on_daily_reset(self, today_date: Any, schedule: Dict[str, Any]) -> None:
        """Reset state internal saat pergantian hari UTC."""
        ...

    def reconcile_broker_orders(self, broker: IBroker, magic_number: int) -> bool:
        """Cek apakah order/posisi strategi sudah ada di broker untuk mencegah duplikasi."""
        ...

    def handle_oco(self, open_positions: List[Any], open_pendings: List[Any], broker: IBroker) -> None:
        """Batalkan pending order yang berlawanan jika salah satu posisi terisi."""
        ...

    def evaluate_entry(
        self,
        df_m5: pd.DataFrame,
        tick: Dict[str, Any],
        equity: float,
        now_utc: datetime,
        schedule: Dict[str, Any],
        open_pendings: Optional[List[Any]] = None,
        broker: Optional[IBroker] = None,
    ) -> Optional[OrderIntent]:
        """Evaluasi kondisi entri live dan kembalikan OrderIntent jika valid."""
        ...

    def evaluate_exit(
        self,
        position: Any,
        df_m5: pd.DataFrame,
        now_utc: datetime,
        broker_utc_offset_sec: int = 0,
        schedule: Optional[Dict[str, Any]] = None,
    ) -> Optional[ExitIntent]:
        """Evaluasi kondisi keluar live dan kembalikan ExitIntent jika valid."""
        ...

    def on_order_result(self, res: OrderResult, broker: Optional[IBroker] = None) -> None:
        """Proses hasil eksekusi order (sukses / requote / gagal)."""
        ...


"""
MT5 Live Connector — Exness Execution Bridge
============================================
Jembatan komunikasi langsung ke MetaTrader 5 untuk streaming data,
pemeriksaan saldo, eksekusi market order, pending stop orders (OCO),
dan manajemen error broker.
"""

from dataclasses import dataclass
from typing import Optional, List, Dict, Any
import datetime
import concurrent.futures
import numpy as np
import pandas as pd
import MetaTrader5 as mt5

from live import live_config as lcfg


@dataclass
class AccountStatus:
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
    success: bool
    retcode: int
    order_id: int
    price: float
    volume: float
    comment: str


def translate_retcode(retcode: int) -> str:
    """Terjemahkan kode retcode MT5 menjadi pesan human-readable."""
    messages = {
        10004: "Requote — Harga pasar bergerak melampaui deviasi",
        10006: "Request rejected by broker",
        10007: "Request canceled by trader",
        10008: "Order placed on broker server",
        10009: "Order executed successfully (Done)",
        10013: "Invalid request format",
        10014: "Invalid volume / lot size",
        10015: "Invalid price",
        10016: "Invalid stops (SL/TP terlalu dekat atau salah posisi)",
        10018: "Market is closed — Pasar sedang tutup",
        10019: "No money / Margin tidak mencukupi untuk membuka lot ini",
        10021: "Off quotes — Broker tidak menyediakan kuotasi harga",
        10027: "ALGO TRADING DISABLED BY CLIENT! Tombol 'Algo Trading' di toolbar MT5 belum diaktifkan.",
    }
    return messages.get(retcode, f"Broker Retcode: {retcode}")


class MT5Connector:
    """Pengelola koneksi dan eksekusi order MetaTrader 5."""

    def __init__(self):
        self.is_connected = False
        self._cached_broker_offset_sec: Optional[int] = None

    def connect(self) -> bool:
        """Inisialisasi koneksi ke terminal MT5 lokal."""
        if not mt5.initialize():
            err = mt5.last_error()
            print(f"[!] Gagal inisialisasi MT5: {err}")
            self.is_connected = False
            return False

        acc = mt5.account_info()
        if not acc:
            print("[!] Tidak ada akun aktif di terminal MT5.")
            self.is_connected = False
            return False

        self.is_connected = True
        return True

    def get_account_status(self) -> Optional[AccountStatus]:
        """Ambil data saldo, ekuitas, dan margin akun."""
        if not self.is_connected and not self.connect():
            return None

        acc = mt5.account_info()
        if not acc:
            return None

        # Periksa izin auto-trading di terminal
        terminal_info = mt5.terminal_info()
        trade_allowed = terminal_info.trade_allowed if terminal_info else True

        return AccountStatus(
            login=acc.login,
            server=acc.server,
            balance=acc.balance,
            equity=acc.equity,
            margin=acc.margin,
            free_margin=acc.margin_free,
            currency=acc.currency,
            trade_allowed=trade_allowed
        )

    def get_symbol_info(self, symbol: str = lcfg.SYMBOL) -> Optional[Any]:
        """Ambil info spesifikasi simbol dari terminal MT5."""
        if not self.is_connected and not self.connect():
            return None
        mt5.symbol_select(symbol, True)
        return mt5.symbol_info(symbol)

    def get_broker_server_utc_offset_seconds(self) -> int:
        """
        Hitung selisih detik antara server broker MT5 dengan UTC (Point P0-003 Audit).
        
        Prioritas:
        1. Konfigurasi manual BROKER_SERVER_OFFSET_HOURS jika tidak 999.
        2. Auto-detect saat market buka via perbandingan tick.time dengan host UTC timestamp.
        3. Fallback cerdas: 0 jika Exness (GMT+0), atau 0 sebagai default aman.
        """
        configured_offset = getattr(lcfg, "BROKER_SERVER_OFFSET_HOURS", 999)
        if configured_offset != 999:
            return configured_offset * 3600

        if self._cached_broker_offset_sec is not None:
            return self._cached_broker_offset_sec

        try:
            tick = mt5.symbol_info_tick(lcfg.SYMBOL)
            if tick:
                now_utc_ts = datetime.datetime.now(datetime.timezone.utc).timestamp()
                age = abs(now_utc_ts - tick.time)
                # Jika tick segar (< 300s, market aktif buka)
                if age < 300:
                    diff_sec = tick.time - now_utc_ts
                    offset_hours = round(diff_sec / 3600.0)
                    self._cached_broker_offset_sec = offset_hours * 3600
                    return self._cached_broker_offset_sec
        except Exception:
            pass

        # Fallback deteksi broker
        acc = self.get_account_status()
        if acc and "exness" in acc.server.lower():
            self._cached_broker_offset_sec = 0
            return 0

        self._cached_broker_offset_sec = 0
        return 0

    def get_tick(self, symbol: str = lcfg.SYMBOL) -> Optional[Dict[str, float]]:
        """Ambil bid, ask, dan spread terkini."""
        if not self.is_connected and not self.connect():
            return None

        mt5.symbol_select(symbol, True)
        tick = mt5.symbol_info_tick(symbol)
        if not tick:
            return None

        spread_usd = round(tick.ask - tick.bid, 3)
        return {
            "bid": tick.bid,
            "ask": tick.ask,
            "spread": spread_usd,
            "time": pd.to_datetime(tick.time, unit="s", utc=True)
        }

    def get_live_rates(self, symbol: str = lcfg.SYMBOL, timeframe=mt5.TIMEFRAME_M5, count: int = 200) -> Optional[pd.DataFrame]:
        """Ambil candle terkini dari MT5 dan kembalikan sebagai DataFrame standar UTC (P0-003)."""
        if not self.is_connected and not self.connect():
            return None

        mt5.symbol_select(symbol, True)
        rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, count)
        if rates is None or len(rates) == 0:
            return None

        df = pd.DataFrame(rates)
        # Selaraskan timezone server broker ke UTC murni
        offset_sec = self.get_broker_server_utc_offset_seconds()
        df["datetime"] = pd.to_datetime(df["time"] - offset_sec, unit="s", utc=True)
        df.rename(columns={"tick_volume": "volume"}, inplace=True)
        df = df[["datetime", "open", "high", "low", "close", "volume"]].copy()
        df.sort_values("datetime", inplace=True)
        df.reset_index(drop=True, inplace=True)
        return df

    def _safe_order_send(self, request: dict, timeout_sec: Optional[float] = None) -> Any:
        """
        Kirim order_send ke MT5 dengan timeout guard via ThreadPoolExecutor.
        Mencegah bot membeku (freeze) jika IPC MT5 hang atau tidak merespons (Point P0-004 Audit).
        """
        if timeout_sec is None:
            timeout_sec = getattr(lcfg, "ORDER_TIMEOUT_SEC", 10.0)

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(mt5.order_send, request)
            try:
                return future.result(timeout=timeout_sec)
            except concurrent.futures.TimeoutError:
                print(f"[💥 IPC TIMEOUT] mt5.order_send() melampaui batas waktu {timeout_sec}s! Mencegah bot freeze.")
                return None

    def get_open_positions(self, magic: int = lcfg.MAGIC_NUMBER) -> List[Any]:
        """Ambil daftar posisi aktif yang dibuka oleh bot."""
        if not self.is_connected and not self.connect():
            return []

        positions = mt5.positions_get(symbol=lcfg.SYMBOL)
        if positions is None:
            return []

        return [p for p in positions if p.magic == magic]

    def get_open_pending_orders(self, magic: int = lcfg.MAGIC_NUMBER) -> List[Any]:
        """Ambil daftar pending orders aktif (Buy Stop / Sell Stop) milik bot."""
        if not self.is_connected and not self.connect():
            return []

        orders = mt5.orders_get(symbol=lcfg.SYMBOL)
        if orders is None:
            return []

        return [o for o in orders if o.magic == magic]

    def get_today_deals(self, magic: int = lcfg.MAGIC_NUMBER) -> List[Any]:
        """Ambil riwayat deal hari ini untuk pemulihan state saat bot restart."""
        if not self.is_connected and not self.connect():
            return []

        now = datetime.datetime.now(datetime.timezone.utc)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = today_start + datetime.timedelta(days=1)
        deals = mt5.history_deals_get(today_start, today_end)
        if deals is None:
            return []
        return [d for d in deals if d.magic == magic]

    def _get_filling_mode(self, symbol: str) -> int:
        """Deteksi tipe order filling yang didukung broker untuk simbol ini."""
        sym_info = self.get_symbol_info(symbol)
        if not sym_info:
            return mt5.ORDER_FILLING_IOC

        fill_flags = sym_info.filling_mode
        # MT5 symbol filling bitmask: 1 = FOK, 2 = IOC
        if fill_flags & 2:
            return getattr(mt5, "ORDER_FILLING_IOC", 1)
        elif fill_flags & 1:
            return getattr(mt5, "ORDER_FILLING_FOK", 0)
        else:
            return getattr(mt5, "ORDER_FILLING_RETURN", 2)

    def open_market_order(
        self,
        direction: str,  # "BUY" atau "SELL"
        volume: float,
        sl: Optional[float] = None,
        tp: Optional[float] = None,
        comment: str = "FLG-Bot",
        symbol: str = lcfg.SYMBOL,
        max_spread: Optional[float] = None
    ) -> OrderResult:
        """Kirim market order ke MT5 Exness."""
        if not self.is_connected and not self.connect():
            return OrderResult(False, -1, 0, 0.0, 0.0, "Not connected to MT5")

        tick = mt5.symbol_info_tick(symbol)
        if not tick:
            return OrderResult(False, -2, 0, 0.0, 0.0, "Failed to get tick")

        # Cek proteksi spread
        spread = tick.ask - tick.bid
        limit_spread = max_spread if max_spread is not None else (lcfg.MAX_SPREAD_USD if symbol == lcfg.SYMBOL else (tick.ask * 0.001))
        if spread > limit_spread:
            return OrderResult(False, -3, 0, 0.0, 0.0, f"Spread melebar: ${spread:.2f} > ${limit_spread:.2f}")

        sym_info = self.get_symbol_info(symbol)
        digits = sym_info.digits if sym_info else 2

        is_buy = (direction.upper() == "BUY")
        order_type = mt5.ORDER_TYPE_BUY if is_buy else mt5.ORDER_TYPE_SELL
        raw_price = tick.ask if is_buy else tick.bid
        price = float(round(raw_price, digits))
        filling = self._get_filling_mode(symbol)

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": float(volume),
            "type": order_type,
            "price": price,
            "deviation": lcfg.SLIPPAGE_POINTS,
            "magic": lcfg.MAGIC_NUMBER,
            "comment": comment,
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": filling,
        }

        if sl is not None and sl > 0:
            request["sl"] = float(round(sl, digits))
        if tp is not None and tp > 0:
            request["tp"] = float(round(tp, digits))

        if lcfg.DRY_RUN:
            print(f"[DRY RUN] Market Order Simulated: {direction} {volume} lots @ {price} | SL: {sl} | TP: {tp}")
            return OrderResult(True, 10009, 999999, price, volume, "Dry run simulated")

        result = self._safe_order_send(request)
        if result is None:
            err = mt5.last_error()
            return OrderResult(False, -4, 0, 0.0, 0.0, f"Order send failed: {err}")

        desc = translate_retcode(result.retcode)
        if result.retcode != mt5.TRADE_RETCODE_DONE:
            return OrderResult(False, result.retcode, result.order, result.price, result.volume, desc)

        return OrderResult(True, result.retcode, result.order, result.price, result.volume, desc)

    def place_pending_order(
        self,
        direction: str,  # "BUY_STOP" atau "SELL_STOP"
        volume: float,
        price: float,
        sl: Optional[float] = None,
        tp: Optional[float] = None,
        comment: str = "FLG-Stop",
        symbol: str = lcfg.SYMBOL
    ) -> OrderResult:
        """Kirim pending stop order langsung ke server MT5 broker (Point #1 Audit)."""
        if not self.is_connected and not self.connect():
            return OrderResult(False, -1, 0, 0.0, 0.0, "Not connected to MT5")

        sym_info = self.get_symbol_info(symbol)
        digits = sym_info.digits if sym_info else 2

        is_buy_stop = (direction.upper() == "BUY_STOP")
        order_type = mt5.ORDER_TYPE_BUY_STOP if is_buy_stop else mt5.ORDER_TYPE_SELL_STOP
        order_price = float(round(price, digits))

        request = {
            "action": mt5.TRADE_ACTION_PENDING,
            "symbol": symbol,
            "volume": float(volume),
            "type": order_type,
            "price": order_price,
            "deviation": lcfg.SLIPPAGE_POINTS,
            "magic": lcfg.MAGIC_NUMBER,
            "comment": comment,
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_RETURN,
        }

        if sl is not None and sl > 0:
            request["sl"] = float(round(sl, digits))
        if tp is not None and tp > 0:
            request["tp"] = float(round(tp, digits))

        if lcfg.DRY_RUN:
            print(f"[DRY RUN] Pending Order Simulated: {direction} {volume} lots @ {order_price} | SL: {sl} | TP: {tp}")
            return OrderResult(True, 10009, 888888, order_price, volume, "Dry run pending simulated")

        result = self._safe_order_send(request)
        if result is None:
            err = mt5.last_error()
            return OrderResult(False, -4, 0, 0.0, 0.0, f"Pending order send failed: {err}")

        desc = translate_retcode(result.retcode)
        if result.retcode != mt5.TRADE_RETCODE_DONE:
            return OrderResult(False, result.retcode, result.order, result.price, result.volume, desc)

        return OrderResult(True, result.retcode, result.order, result.price, result.volume, desc)

    def cancel_pending_order(self, order_id: int) -> OrderResult:
        """Batalkan pending order yang belum terpicu di server broker."""
        if not self.is_connected and not self.connect():
            return OrderResult(False, -1, 0, 0.0, 0.0, "Not connected")

        if lcfg.DRY_RUN:
            print(f"[DRY RUN] Canceled Pending Order Ticket {order_id}")
            return OrderResult(True, 10009, order_id, 0.0, 0.0, "Dry run canceled")

        request = {
            "action": mt5.TRADE_ACTION_REMOVE,
            "order": order_id
        }
        result = self._safe_order_send(request)
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            ret = result.retcode if result else -6
            desc = translate_retcode(ret)
            return OrderResult(False, ret, order_id, 0.0, 0.0, desc)

        return OrderResult(True, result.retcode, result.order, 0.0, 0.0, "Pending order removed successfully")

    def close_position(self, ticket: int, comment: str = "Close Bot") -> OrderResult:
        """Tutup posisi aktif berdasarkan tiket."""
        if not self.is_connected and not self.connect():
            return OrderResult(False, -1, 0, 0.0, 0.0, "Not connected")

        positions = mt5.positions_get(ticket=ticket)
        if not positions or len(positions) == 0:
            return OrderResult(False, -5, ticket, 0.0, 0.0, "Position not found")

        pos = positions[0]
        is_buy = (pos.type == mt5.ORDER_TYPE_BUY)
        close_type = mt5.ORDER_TYPE_SELL if is_buy else mt5.ORDER_TYPE_BUY
        tick = mt5.symbol_info_tick(pos.symbol)
        if not tick:
            return OrderResult(False, -2, ticket, 0.0, 0.0, "Tick unavailable")

        sym_info = self.get_symbol_info(pos.symbol)
        digits = sym_info.digits if sym_info else 2

        raw_price = tick.bid if is_buy else tick.ask
        close_price = float(round(raw_price, digits))
        filling = self._get_filling_mode(pos.symbol)

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": pos.symbol,
            "volume": pos.volume,
            "type": close_type,
            "position": ticket,
            "price": close_price,
            "deviation": lcfg.SLIPPAGE_POINTS,
            "magic": lcfg.MAGIC_NUMBER,
            "comment": comment,
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": filling,
        }

        if lcfg.DRY_RUN:
            print(f"[DRY RUN] Closed Ticket {ticket} @ {close_price}")
            return OrderResult(True, 10009, ticket, close_price, pos.volume, "Dry run close")

        result = self._safe_order_send(request)
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            ret = result.retcode if result else -6
            desc = translate_retcode(ret)
            return OrderResult(False, ret, ticket, close_price, pos.volume, desc)

        return OrderResult(True, result.retcode, result.order, result.price, result.volume, "Position closed successfully")

    def shutdown(self):
        """Putuskan koneksi dari MT5."""
        if self.is_connected:
            mt5.shutdown()
            self.is_connected = False

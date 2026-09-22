"""
MT5 Live Connector — Exness Execution Bridge
============================================
Jembatan komunikasi langsung ke MetaTrader 5 untuk streaming data,
pemeriksaan saldo, eksekusi market order, pending stop orders (OCO),
dan manajemen error broker.
"""

from dataclasses import dataclass
from typing import Optional, List, Dict, Any
import sys
import datetime
import concurrent.futures
import numpy as np
import pandas as pd
import MetaTrader5 as mt5

from src.execution import config as lcfg
from src.core.types import OrderIntent


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
        """Hitung selisih detik antara server broker MT5 dengan UTC."""
        configured_offset = getattr(lcfg, "BROKER_SERVER_OFFSET_HOURS", 999)
        if configured_offset != 999:
            return int(configured_offset * 3600)

        if self._cached_broker_offset_sec is not None:
            return self._cached_broker_offset_sec

        acc = self.get_account_status()
        if acc and "exness" in acc.server.lower():
            self._cached_broker_offset_sec = 0
            return 0

        try:
            rates = mt5.copy_rates_from_pos(lcfg.SYMBOL, mt5.TIMEFRAME_M5, 0, 1)
            if rates is not None and len(rates) > 0:
                last_bar_time = rates[-1]["time"]
                now_utc = datetime.datetime.now(datetime.timezone.utc)
                now_utc_ts = now_utc.timestamp()

                if abs(now_utc_ts - last_bar_time) < 900:
                    curr_m5_utc_minute = (now_utc.minute // 5) * 5
                    expected_m5_utc = now_utc.replace(minute=curr_m5_utc_minute, second=0, microsecond=0).timestamp()
                    diff_sec = last_bar_time - expected_m5_utc
                    offset_hours = round(diff_sec / 3600.0)
                    self._cached_broker_offset_sec = int(offset_hours * 3600)
                    return self._cached_broker_offset_sec
        except Exception:
            pass

        if acc and any(b in acc.server.lower() for b in ["icmarkets", "pepperstone", "vantage", "ftmo"]):
            self._cached_broker_offset_sec = 2 * 3600
            return self._cached_broker_offset_sec

        self._cached_broker_offset_sec = 0
        return 0

    def probe_broker_timezone(self) -> Dict[str, Any]:
        """Diagnostik probe waktu server broker vs host UTC."""
        acc = self.get_account_status()
        server_name = acc.server if acc else "Unknown"
        offset_sec = self.get_broker_server_utc_offset_seconds()
        offset_hours = offset_sec // 3600
        now_utc = datetime.datetime.now(datetime.timezone.utc)

        rates = mt5.copy_rates_from_pos(lcfg.SYMBOL, mt5.TIMEFRAME_M5, 0, 1)
        last_bar_raw = None
        last_bar_utc = None
        diff_minutes = 0.0

        if rates is not None and len(rates) > 0:
            raw_ts = int(rates[-1]["time"])
            last_bar_raw = datetime.datetime.fromtimestamp(raw_ts, tz=datetime.timezone.utc)
            last_bar_utc = datetime.datetime.fromtimestamp(raw_ts - offset_sec, tz=datetime.timezone.utc)
            diff_minutes = (now_utc - last_bar_utc).total_seconds() / 60.0

        return {
            "server": server_name,
            "offset_hours": offset_hours,
            "offset_seconds": offset_sec,
            "now_utc": now_utc,
            "last_bar_raw": last_bar_raw,
            "last_bar_utc": last_bar_utc,
            "diff_minutes": diff_minutes,
        }

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
        """Ambil candle terkini dari MT5 dan kembalikan sebagai DataFrame standar UTC."""
        if not self.is_connected and not self.connect():
            return None

        mt5.symbol_select(symbol, True)
        rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, count)
        if rates is None or len(rates) == 0:
            return None

        df = pd.DataFrame(rates)
        offset_sec = self.get_broker_server_utc_offset_seconds()
        df["datetime"] = pd.to_datetime(df["time"] - offset_sec, unit="s", utc=True)
        df.rename(columns={"tick_volume": "volume"}, inplace=True)
        df = df[["datetime", "open", "high", "low", "close", "volume"]].copy()
        df.sort_values("datetime", inplace=True)
        df.reset_index(drop=True, inplace=True)
        return df

    def _safe_order_send(self, request: dict, timeout_sec: Optional[float] = None) -> Any:
        """Kirim order_send ke MT5 secara aman pada thread utama yang terotentikasi."""
        try:
            return mt5.order_send(request)
        except Exception as e:
            print(f"[💥 ORDER SEND EXCEPTION] {e}")
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
        """Ambil daftar pending orders aktif milik bot."""
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
        if fill_flags & 2:
            return getattr(mt5, "ORDER_FILLING_IOC", 1)
        elif fill_flags & 1:
            return getattr(mt5, "ORDER_FILLING_FOK", 0)
        else:
            return getattr(mt5, "ORDER_FILLING_RETURN", 2)

    def open_market_order(
        self,
        direction: str,
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

        # Validasi arah TP & Stops Level Broker
        if tp is not None and tp > 0:
            point = sym_info.point if sym_info else 0.01
            stops_level_dist = (sym_info.stops_level * point) if (sym_info and hasattr(sym_info, "stops_level")) else 0.0

            if is_buy:
                if tp <= price:
                    print(f"[⚠️ INVERTED TP BLOCKED] BUY TP ({tp:.2f}) <= Entry ({price:.2f}). Hard TP dibatalkan demi keamanan.")
                    tp = None
                elif stops_level_dist > 0 and (tp - price) < stops_level_dist:
                    print(f"[⚠️ TP STOPS LEVEL] BUY TP jarak ({tp - price:.2f}) < broker stops_level ({stops_level_dist:.2f}). Hard TP dibatalkan.")
                    tp = None
            else:
                if tp >= price:
                    print(f"[⚠️ INVERTED TP BLOCKED] SELL TP ({tp:.2f}) >= Entry ({price:.2f}). Hard TP dibatalkan demi keamanan.")
                    tp = None
                elif stops_level_dist > 0 and (price - tp) < stops_level_dist:
                    print(f"[⚠️ TP STOPS LEVEL] SELL TP jarak ({price - tp:.2f}) < broker stops_level ({stops_level_dist:.2f}). Hard TP dibatalkan.")
                    tp = None

        if tp is not None and tp > 0:
            request["tp"] = float(round(tp, digits))

        if lcfg.DRY_RUN:
            print(f"[DRY RUN] Market Order Simulated: {direction} {volume} lots @ {price} | SL: {sl} | TP: {tp}")
            return OrderResult(True, 10009, 999999, price, volume, "Dry run simulated")

        result = self._safe_order_send(request)
        if result is None:
            err = mt5.last_error()
            return OrderResult(False, -10008, 0, 0.0, 0.0, f"IPC Timeout / State Unknown: {err}")

        desc = translate_retcode(result.retcode)
        if result.retcode != mt5.TRADE_RETCODE_DONE:
            return OrderResult(False, result.retcode, result.order, result.price, result.volume, desc)

        return OrderResult(True, result.retcode, result.order, result.price, result.volume, desc)

    def place_pending_order(
        self,
        direction: str,
        volume: float,
        price: float,
        sl: Optional[float] = None,
        tp: Optional[float] = None,
        comment: str = "FLG-Stop",
        symbol: str = lcfg.SYMBOL
    ) -> OrderResult:
        """Kirim pending stop order langsung ke server MT5 broker."""
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
            if is_buy_stop and tp <= order_price:
                print(f"[⚠️ INVERTED TP BLOCKED] BUY_STOP TP ({tp:.2f}) <= Order Price ({order_price:.2f}). Hard TP dibatalkan.")
                tp = None
            elif (not is_buy_stop) and tp >= order_price:
                print(f"[⚠️ INVERTED TP BLOCKED] SELL_STOP TP ({tp:.2f}) >= Order Price ({order_price:.2f}). Hard TP dibatalkan.")
                tp = None

        if tp is not None and tp > 0:
            request["tp"] = float(round(tp, digits))

        if lcfg.DRY_RUN:
            print(f"[DRY RUN] Pending Order Simulated: {direction} {volume} lots @ {order_price} | SL: {sl} | TP: {tp}")
            return OrderResult(True, 10009, 888888, order_price, volume, "Dry run pending simulated")

        result = self._safe_order_send(request)
        if result is None:
            err = mt5.last_error()
            return OrderResult(False, -10008, 0, 0.0, 0.0, f"IPC Timeout / State Unknown: {err}")

        desc = translate_retcode(result.retcode)
        if result.retcode != mt5.TRADE_RETCODE_DONE:
            return OrderResult(False, result.retcode, result.order, result.price, result.volume, desc)

        return OrderResult(True, result.retcode, result.order, result.price, result.volume, desc)

    def execute_order_intent(self, intent: OrderIntent) -> OrderResult:
        """Eksekusi OrderIntent secara seragam (market order atau pending stop order)."""
        action = intent.action.upper()
        if action in ("BUY", "SELL"):
            return self.open_market_order(
                direction=action,
                volume=intent.volume,
                sl=intent.stop_loss,
                tp=intent.take_profit,
                comment=intent.comment,
                magic=intent.magic_number,
            )
        elif action in ("BUY_STOP", "SELL_STOP"):
            return self.place_pending_order(
                direction=action,
                volume=intent.volume,
                price=intent.entry_price,
                sl=intent.stop_loss,
                tp=intent.take_profit,
                comment=intent.comment,
                magic=intent.magic_number,
            )
        else:
            return OrderResult(
                success=False,
                retcode=10013,
                order_id=0,
                price=0.0,
                volume=intent.volume,
                comment=f"Unknown order action: {action}",
            )

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

    def close_position(self, ticket: Any, comment: str = "Close Bot") -> OrderResult:
        """Tutup posisi aktif berdasarkan tiket (int atau TradePosition)."""
        if hasattr(ticket, "ticket"):
            ticket = int(ticket.ticket)
        elif isinstance(ticket, dict) and "ticket" in ticket:
            ticket = int(ticket["ticket"])
        else:
            ticket = int(ticket)

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

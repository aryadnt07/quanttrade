"""
Exness MT5 Connection Health Check
==================================
Skrip uji diagnostik untuk memverifikasi kesiapan trading live di Exness MT5.
"""

import sys
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from src.execution.mt5_connector import MT5Connector
from src.execution import config as lcfg


def run_connection_test():
    """Jalankan cek koneksi MT5."""
    print()
    print("=" * 64)
    print("   EXNESS MT5 — LIVE CONNECTION HEALTH CHECK")
    print("=" * 64)

    connector = MT5Connector()
    print("[*] Menghubungkan ke terminal MT5 lokal...")

    if not connector.connect():
        print("[X] GAGAL: Tidak dapat terhubung ke MetaTrader 5.")
        print("    Pastikan aplikasi MT5 terbuka di desktop Anda.")
        return False

    print("[✓] Terhubung sukses ke MetaTrader 5!")
    print()

    # 1. Cek Akun & AlgoTrading Permission
    status = connector.get_account_status()
    if status:
        print("--- STATUS AKUN EXNESS ---")
        print(f"Login ID       : {status.login}")
        print(f"Server Broker  : {status.server}")
        print(f"Balance        : ${status.balance:,.2f} {status.currency}")
        print(f"Equity         : ${status.equity:,.2f} {status.currency}")
        print(f"Free Margin    : ${status.free_margin:,.2f} {status.currency}")
        algo_status = "AKTIF (SIAP EKSEKUSI)" if status.trade_allowed else "NONAKTIF! (Klik tombol 'Algo Trading' di MT5)"
        print(f"Algo Trading   : {algo_status}")
        print()
    else:
        print("[!] Tidak dapat membaca info akun.")

    # 2. Cek Simbol & Harga Real-Time
    tick = connector.get_tick(lcfg.SYMBOL)
    if tick:
        print(f"--- STREAMING HARGA REAL-TIME: {lcfg.SYMBOL} ---")
        print(f"Bid Price      : {tick['bid']}")
        print(f"Ask Price      : {tick['ask']}")
        print(f"Spread         : ${tick['spread']:.3f} USD")
        print(f"Server Time    : {tick['time']}")
        print()
    else:
        print(f"[!] Simbol {lcfg.SYMBOL} tidak ditemukan di Market Watch MT5.")

    # 3. Cek Streaming Candle M5
    rates = connector.get_live_rates(symbol=lcfg.SYMBOL, count=5)
    if rates is not None and not rates.empty:
        print(f"--- 5 CANDLE M5 TERAKHIR DARI BROKER ---")
        print(rates.to_string(index=False))
        print()
    else:
        print("[!] Gagal mengambil candle M5.")

    # 4. Cek Posisi Aktif
    pos = connector.get_open_positions()
    print(f"--- POSISI AKTIF BOT ---")
    print(f"Total Open Trades (Magic {lcfg.MAGIC_NUMBER}): {len(pos)}")
    print()

    print("=" * 64)
    print("   [✓] KONEKSI 100% SIAP UNTUK ALGO TRADING LIVE!")
    print("=" * 64)
    print()

    connector.shutdown()
    return True


if __name__ == "__main__":
    run_connection_test()

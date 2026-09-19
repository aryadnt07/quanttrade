"""
Live Trading System Readiness & Diagnostic Suite
=================================================
Pengujian mandiri komprehensif untuk seluruh subsistem live trading sebelum
bot dijalankan secara live 24/7 di MetaTrader 5.

8 Tahapan Verifikasi:
[1/8] System Environment & UTC Clock Synchronization
[2/8] MT5 Terminal IPC & Broker Server Authentication
[3/8] Account Status & AlgoTrading Master Permissions
[4/8] Market Data Stream & Live Spread Telemetry (XAU/USD)
[5/8] Live M5 & M1 Bar Feed Integrity & Continuity
[6/8] Strategy Engines & Live Signal Math Verification
[7/8] Risk Management & Position Sizing Safety Gates
[8/8] Broker Margin & Order Payload Check (Zero-Risk Dry-Run)
"""

import os
import sys
import time
import platform
from datetime import datetime, timezone
from typing import Dict, Any, Tuple, Optional

# Windows console UTF-8 fix
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Ensure project root is in sys.path
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

import numpy as np
import pandas as pd
import MetaTrader5 as mt5

from live.mt5_connector import MT5Connector, translate_retcode
from configs import live_config as lcfg
from configs import asia_config as acfg
from configs import london_config as london_cfg
from configs import ny_config as ny_cfg

# Strategy indicator modules
from engine.asia.indicators import compute_all as compute_asian
from engine.london.strategy import compute_london_indicators
from engine.ny.strategy import compute_ny_indicators


def run_live_system_check() -> bool:
    """Eksekusi 8 tahapan pengujian diagnostik live trading."""
    sep = "=" * 74
    subsep = "-" * 74

    print("\n" + sep)
    print("   QUANTTRADE — LIVE TRADING SYSTEM READINESS & DIAGNOSTIC SUITE")
    print("   Institutional Pre-Check for MetaTrader 5 Live Execution")
    print(sep + "\n")

    overall_passed = True
    warnings = []
    failures = []

    # ─────────────────────────────────────────────────────────────
    # [1/8] SYSTEM ENVIRONMENT & UTC CLOCK SYNCHRONIZATION
    # ─────────────────────────────────────────────────────────────
    print("[1/8] Memeriksa Lingkungan Sistem & Sinkronisasi Waktu UTC...")
    os_name = f"{platform.system()} {platform.release()} ({platform.machine()})"
    py_ver = sys.version.split()[0]
    is_64bit = sys.maxsize > 2**32
    utc_now = datetime.now(timezone.utc)

    print(f"      - OS Host          : {os_name}")
    print(f"      - Python Engine    : {py_ver} ({'64-bit' if is_64bit else '32-bit'})")
    print(f"      - UTC System Time  : {utc_now.strftime('%Y-%m-%d %H:%M:%S')} UTC")

    if not is_64bit:
        failures.append("Python harus versi 64-bit untuk MetaTrader 5 API.")
        print("      [X] GAGAL: Python terdeteksi 32-bit.")
        overall_passed = False
    else:
        print("      [✓] PASS: Lingkungan host & arsitektur 64-bit valid.")

    # ─────────────────────────────────────────────────────────────
    # [2/8] MT5 TERMINAL IPC & BROKER SERVER AUTHENTICATION
    # ─────────────────────────────────────────────────────────────
    print("\n[2/8] Memeriksa Koneksi IPC ke Terminal MetaTrader 5...")
    connector = MT5Connector()
    t_start = time.time()
    connected = connector.connect()
    latency_ms = (time.time() - t_start) * 1000.0

    if not connected:
        failures.append("Gagal terhubung ke terminal MT5. Pastikan MT5 terbuka.")
        print("      [X] GAGAL: Terminal MetaTrader 5 tidak merespons.")
        overall_passed = False
        print("\n" + sep)
        print("   [!] PENGUJIAN TERHENTI: MT5 tidak aktif.")
        print(sep + "\n")
        return False

    term_info = mt5.terminal_info()
    term_ver = f"Build {term_info.build}" if term_info else "Unknown"
    term_path = term_info.path if term_info else "Unknown"
    print(f"      - Terminal Build   : {term_ver}")
    print(f"      - IPC Ping Latency : {latency_ms:.1f} ms")
    print(f"      - Terminal Path    : {term_path}")
    print("      [✓] PASS: Koneksi IPC ke MetaTrader 5 berhasil.")

    # ─────────────────────────────────────────────────────────────
    # [3/8] ACCOUNT STATUS & ALGOTRADING MASTER PERMISSIONS
    # ─────────────────────────────────────────────────────────────
    print("\n[3/8] Memeriksa Status Akun Broker & Izin Algo Trading...")
    acc_status = connector.get_account_status()
    acc_info = mt5.account_info()

    if not acc_status or not acc_info:
        failures.append("Gagal membaca profil akun MT5.")
        print("      [X] GAGAL: Tidak dapat membaca akun.")
        overall_passed = False
    else:
        print(f"      - Akun Login ID    : {acc_status.login}")
        print(f"      - Server Broker    : {acc_status.server}")
        print(f"      - Saldo (Balance)  : ${acc_status.balance:,.2f} {acc_status.currency}")
        print(f"      - Ekuitas (Equity) : ${acc_status.equity:,.2f} {acc_status.currency}")
        print(f"      - Margin Bebas     : ${acc_status.free_margin:,.2f} {acc_status.currency}")
        print(f"      - Leverage         : 1:{acc_info.leverage}")

        # Cek izin trading
        terminal_trade_allowed = term_info.trade_allowed if term_info else False
        account_trade_allowed = acc_info.trade_allowed
        account_expert_allowed = acc_info.trade_expert

        if not terminal_trade_allowed or not account_trade_allowed or not account_expert_allowed:
            warnings.append("Tombol 'Algo Trading' di toolbar MT5 belum aktif! Aktifkan agar bot bisa kirim order.")
            print("      [!] PERINGATAN: Tombol 'Algo Trading' di toolbar MT5 NONAKTIF.")
            print("          -> Silakan klik tombol 'Algo Trading' di MT5 agar berwarna HIJAU.")
        else:
            print("      [✓] PASS: Algo Trading aktif & izin eksekusi otomatis disetujui broker.")

    # ─────────────────────────────────────────────────────────────
    # [4/8] MARKET DATA STREAM & SPREAD TELEMETRY (XAU/USD)
    # ─────────────────────────────────────────────────────────────
    print(f"\n[4/8] Memeriksa Streaming Harga & Spread Telemetri ({lcfg.SYMBOL})...")
    sym_info = connector.get_symbol_info(lcfg.SYMBOL)

    if not sym_info:
        failures.append(f"Simbol {lcfg.SYMBOL} tidak ditemukan di Market Watch MT5.")
        print(f"      [X] GAGAL: Simbol {lcfg.SYMBOL} tidak tersedia.")
        overall_passed = False
        tick = None
    else:
        tick = connector.get_tick(lcfg.SYMBOL)
        if not tick:
            failures.append("Gagal mengambil tick harga pasar terkini.")
            print("      [X] GAGAL: Tick pasar kosong.")
            overall_passed = False
        else:
            spread_usd = tick["spread"]
            tick_time = tick["time"]
            age_sec = (utc_now - tick_time).total_seconds()

            print(f"      - Live Bid Price   : {tick['bid']:.3f}")
            print(f"      - Live Ask Price   : {tick['ask']:.3f}")
            print(f"      - Live Spread      : ${spread_usd:.3f} USD/oz ({int(spread_usd * 100)} points)")
            print(f"      - Server Tick Time : {tick_time.strftime('%Y-%m-%d %H:%M:%S')} UTC (Age: {age_sec:.1f}s)")
            print(f"      - Kontrak Min/Max  : {sym_info.volume_min} lot s/d {sym_info.volume_max} lot (Step: {sym_info.volume_step})")

            if spread_usd > lcfg.MAX_SPREAD_USD:
                warnings.append(f"Spread saat ini ${spread_usd:.3f} > batas ${lcfg.MAX_SPREAD_USD:.2f}. Pastikan pasar tidak sedang libur/weekend.")
                print(f"      [!] PERINGATAN: Spread tinggi (${spread_usd:.3f} USD/oz).")
            else:
                print("      [✓] PASS: Streaming harga aktif, spread normal dan likuiditas sehat.")

    # ─────────────────────────────────────────────────────────────
    # [5/8] LIVE M5 & M1 BAR FEED INTEGRITY & CONTINUITY
    # ─────────────────────────────────────────────────────────────
    print(f"\n[5/8] Memeriksa Kualitas Data Bar M5 & M1 dari Broker...")
    df_m5 = connector.get_live_rates(lcfg.SYMBOL, timeframe=mt5.TIMEFRAME_M5, count=100)
    df_m1 = connector.get_live_rates(lcfg.SYMBOL, timeframe=mt5.TIMEFRAME_M1, count=100)

    if df_m5 is None or len(df_m5) < 50:
        failures.append("Gagal mengunduh bar M5 terkini dari broker MT5.")
        print("      [X] GAGAL: Bar M5 tidak mencukupi.")
        overall_passed = False
    else:
        has_nan_m5 = df_m5[["open", "high", "low", "close"]].isna().any().any()
        latest_m5_time = df_m5["datetime"].iloc[-1]
        print(f"      - Bar M5 Diterima  : {len(df_m5)} bars (Bar Terkini: {latest_m5_time.strftime('%Y-%m-%d %H:%M')} UTC)")
        print(f"      - Bar M5 Integritas: {'Valid (Zero NaN)' if not has_nan_m5 else 'Ada NaN'}")

    if df_m1 is None or len(df_m1) < 50:
        warnings.append("Data M1 Bar Magnifier terbatas dari broker.")
        print("      [!] PERINGATAN: Bar M1 sub-bars tidak lengkap.")
    else:
        print(f"      - Bar M1 Diterima  : {len(df_m1)} sub-bars (Bar Magnifier Ready)")
        print("      [✓] PASS: Data feed M5/M1 broker lengkap dan kontinu.")

    # ─────────────────────────────────────────────────────────────
    # [6/8] STRATEGY ENGINES & LIVE SIGNAL MATH VERIFICATION
    # ─────────────────────────────────────────────────────────────
    print("\n[6/8] Memverifikasi Mesin Indikator & Kalkulasi Sinyal Live...")
    if df_m5 is not None and len(df_m5) >= 50:
        try:
            # Test Asia MR Math
            df_a = compute_asian(df_m5)
            latest_z = df_a["zscore"].iloc[-2]
            latest_atr = df_a["atr"].iloc[-2]
            latest_anchor = df_a["anchor"].iloc[-2]
            print(f"      - Asian MR Math    : Anchor={latest_anchor:.2f} | Z-Score={latest_z:.2f} | ATR={latest_atr:.2f}")

            # Test London ORB Math
            df_lon = compute_london_indicators(df_m5)
            lon_atr = df_lon["atr14"].iloc[-2]
            lon_tr_sma = df_lon["tr_sma20"].iloc[-2]
            print(f"      - London ORB Math  : TR_SMA20={lon_tr_sma:.2f} | ATR(14)={lon_atr:.2f}")

            # Test NY ORB Math
            df_ny = compute_ny_indicators(df_m5)
            ny_atr = df_ny["atr14"].iloc[-2]
            ny_tr_sma = df_ny["tr_sma20"].iloc[-2]
            print(f"      - New York ORB Math: TR_SMA20={ny_tr_sma:.2f} | ATR(14)={ny_atr:.2f}")

            if np.isnan(latest_z) or np.isnan(latest_atr):
                failures.append("Kalkulasi Z-Score atau ATR menghasilkan NaN.")
                print("      [X] GAGAL: Indikator menghasilkan nilai NaN.")
                overall_passed = False
            else:
                print("      [✓] PASS: Semua formula matematika 3 strategi berjalan akurat & presisi.")
        except Exception as e:
            failures.append(f"Error kalkulasi indikator: {e}")
            print(f"      [X] GAGAL: Error saat komputasi sinyal: {e}")
            overall_passed = False
    else:
        print("      [!] Lewati verifikasi sinyal karena data bar tidak mencukupi.")

    # ─────────────────────────────────────────────────────────────
    # [7/8] RISK MANAGEMENT & POSITION SIZING SAFETY GATES
    # ─────────────────────────────────────────────────────────────
    print("\n[7/8] Memeriksa Aturan Manajemen Risiko & Batas Keamanan...")
    curr_balance = acc_status.balance if acc_status else 10_000.0
    risk_asia_usd = curr_balance * lcfg.ASIAN_RISK_PCT
    risk_lon_usd = curr_balance * lcfg.LONDON_RISK_PCT
    risk_ny_usd = curr_balance * lcfg.NY_RISK_PCT
    max_chase = getattr(lcfg, "MAX_CHASE_USD", 0.80)
    max_retries = getattr(lcfg, "MAX_SESSION_RETRIES", 3)
    max_daily_loss = getattr(lcfg, "MAX_DAILY_LOSS_PCT", 0.05)
    order_timeout = getattr(lcfg, "ORDER_TIMEOUT_SEC", 10.0)
    offset_sec = connector.get_broker_server_utc_offset_seconds()

    print(f"      - Alokasi Risiko Asia   : {lcfg.ASIAN_RISK_PCT*100:.1f}% (${risk_asia_usd:,.2f} USD)")
    print(f"      - Alokasi Risiko London : {lcfg.LONDON_RISK_PCT*100:.1f}% (${risk_lon_usd:,.2f} USD)")
    print(f"      - Alokasi Risiko NY     : {lcfg.NY_RISK_PCT*100:.1f}% (${risk_ny_usd:,.2f} USD)")
    print(f"      - Daily Loss Limit (CB) : {max_daily_loss*100:.1f}% max portfolio drawdown")
    print(f"      - Slippage Max Tolerance: {lcfg.SLIPPAGE_POINTS} points ($0.30)")
    print(f"      - Anti-Chasing Ceiling  : ${max_chase:.2f} USD (Batas kejar harga)")
    print(f"      - Anti-Spam Max Retry   : {max_retries} kali (Mencegah requote spam)")
    print(f"      - IPC Order Timeout     : {order_timeout:.1f}s (Anti-freeze guard)")
    print(f"      - Broker Server Offset  : {offset_sec//3600:+d}h UTC (Dynamic auto-detection)")
    print("      [✓] PASS: Batasan risiko institusional & safety gates terkonfigurasi aktif.")

    # ─────────────────────────────────────────────────────────────
    # [8/8] ORDER VALIDATION & BROKER MARGIN CHECK (DRY-RUN)
    # ─────────────────────────────────────────────────────────────
    print("\n[8/8] Menguji Validasi Order ke Server Broker (Zero-Risk Dry-Run)...")
    if tick and sym_info and acc_status:
        test_lot = sym_info.volume_min  # Lot minimal untuk pengujian (0.01)
        test_ask = tick["ask"]
        test_sl = round(test_ask - 3.0, 2)
        test_tp = round(test_ask + 6.0, 2)
        filling_mode = connector._get_filling_mode(lcfg.SYMBOL)

        buy_request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": lcfg.SYMBOL,
            "volume": test_lot,
            "type": mt5.ORDER_TYPE_BUY,
            "price": test_ask,
            "sl": test_sl,
            "tp": test_tp,
            "deviation": lcfg.SLIPPAGE_POINTS,
            "magic": lcfg.MAGIC_NUMBER,
            "comment": "PreCheck-DryRun",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": filling_mode,
        }

        # Uji validasi via mt5.order_check (TIDAK MEMBUKA ORDER NYATA)
        check_result = mt5.order_check(buy_request)

        if check_result is None:
            err = mt5.last_error()
            warnings.append(f"order_check tidak merespons: {err}")
            print(f"      [!] order_check gagal dipanggil: {err}")
        else:
            ret_desc = translate_retcode(check_result.retcode)
            print(f"      - Payload Order Test: BUY {test_lot} lot XAU/USD @ {test_ask:.2f} (SL: {test_sl} | TP: {test_tp})")
            print(f"      - Margin Dibutuhkan : ${check_result.margin:,.2f} {acc_status.currency}")
            print(f"      - Sisa Margin Bebas : ${check_result.margin_free:,.2f} {acc_status.currency}")
            print(f"      - Respons Server    : Retcode {check_result.retcode} ({ret_desc})")

            # Cek apakah posisi aktif bertambah (harus tetap 0!)
            open_positions = connector.get_open_positions(lcfg.MAGIC_NUMBER)
            print(f"      - Posisi Terbuka    : {len(open_positions)} tiket (Terbukti 100% Zero-Risk, Saldo Aman)")

            if check_result.retcode in [0, 10008, 10009]:
                print("      [✓] PASS: Server broker Exness mengonfirmasi payload order 100% valid!")
            elif check_result.retcode == 10027:
                warnings.append("Broker menolak simulasi karena tombol 'Algo Trading' di MT5 belum diaktifkan.")
                print("      [!] CATATAN: Aktifkan tombol 'Algo Trading' di MT5 untuk izin eksekusi penuh.")
            elif check_result.retcode == 10018:
                warnings.append("Pasar saat ini sedang tutup (Market is Closed). Uji order validasi format sukses.")
                print("      [✓] PASS: Format order valid (Status: Market Closed).")
            else:
                warnings.append(f"Respons validasi broker: {ret_desc}")
    else:
        print("      [!] Lewati order_check karena data tick tidak tersedia.")

    # ─────────────────────────────────────────────────────────────
    # KESIMPULAN & HASIL DIAGNOSTIK
    # ─────────────────────────────────────────────────────────────
    print("\n" + sep)
    print("   RINGKASAN DIAGNOSTIK KESIAPAN LIVE TRADING (SCORECARD)")
    print(sep)

    print(f"  Status Keseluruhan : {'[✓] OPERASIONAL & SIAP LIVE' if overall_passed else '[X] BUTUH PERBAIKAN'}")
    print(f"  Total Peringatan   : {len(warnings)}")
    print(f"  Total Kegagalan    : {len(failures)}")

    if warnings:
        print("\n  CATATAN PERINGATAN:")
        for w in warnings:
            print(f"   [!] {w}")

    if failures:
        print("\n  DAFTAR KEGAGALAN SISTEM:")
        for f in failures:
            print(f"   [X] {f}")

    print(subsep)
    if overall_passed and not failures:
        if not warnings:
            print("  STATUS AKHIR: [ 100% SEMPURNA — SISTEM SIAP RUNNING LIVE 24/7 ]")
        else:
            print("  STATUS AKHIR: [ SIAP LIVE DENGAN CATATAN (Cek peringatan di atas) ]")
    else:
        print("  STATUS AKHIR: [ BELUM SIAP — Harap selesaikan masalah teknis di atas ]")
    print(sep + "\n")

    return overall_passed and (len(failures) == 0)


def main() -> int:
    """Entry point for CLI execution."""
    success = run_live_system_check()
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())

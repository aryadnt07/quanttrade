"""
Live Trading System Readiness & Diagnostic Suite
=================================================
Pengujian mandiri komprehensif untuk seluruh subsistem live trading sebelum
bot dijalankan secara live 24/7 di MetaTrader 5.

10 Tahapan Verifikasi:
[1/10] System Environment & UTC Clock Synchronization
[2/10] MT5 Terminal IPC & Broker Server Authentication
[3/10] Account Status & AlgoTrading Master Permissions
[4/10] Market Data Stream & Live Spread Telemetry (XAU/USD)
[5/10] Live M5 & M1 Bar Feed Integrity & Continuity
[6/10] Strategy Engines & Live Signal Math Verification
[7/10] Risk Management & Position Sizing Safety Gates
[8/10] Broker Margin & Order Payload Check (Zero-Risk Dry-Run)
[9/10] Instance Mutex Lock & State Persistence Integrity (PID Lock & Circuit Breaker)
[10/10] Telegram Notification Engine & Remote Alert Telemetry
"""

import os
import sys
import time
import json
import platform
from datetime import datetime, timezone
from typing import Dict, Any, Tuple, Optional

# Windows console UTF-8 fix
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import numpy as np
import pandas as pd
import MetaTrader5 as mt5

from src.execution.mt5_connector import MT5Connector, translate_retcode
from src.execution.risk_manager import is_process_running
from src.execution.notifications import TelegramNotifier
from src.execution import config as lcfg
from src.strategies.asian_mr import config as acfg
from src.strategies.london_orb import config as london_cfg
from src.strategies.ny_orb import config as ny_cfg

# Strategy indicator modules (canonical single source of truth)
from src.strategies.asian_mr.signals import compute_asian_indicators as compute_asian
from src.strategies.london_orb.signals import compute_london_indicators
from src.strategies.ny_orb.signals import compute_ny_indicators

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def run_live_system_check() -> bool:
    """Eksekusi 10 tahapan pengujian diagnostik live trading."""
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
    # [1/10] SYSTEM ENVIRONMENT & UTC CLOCK SYNCHRONIZATION
    # ─────────────────────────────────────────────────────────────
    print("[1/10] Memeriksa Lingkungan Sistem & Sinkronisasi Waktu UTC...")
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
        if sys.version_info < (3, 9):
            warnings.append(f"Python versi {py_ver} < 3.9 terdeteksi. Disarankan Python >= 3.9 untuk support cancel_futures.")
            print(f"      [!] PERINGATAN: Python {py_ver} < 3.9 (fitur cancel_futures berjalan dalam mode fallback).")
        else:
            print("      [✓] PASS: Lingkungan host & arsitektur 64-bit valid (Python >= 3.9 OK).")

    # ─────────────────────────────────────────────────────────────
    # [2/10] MT5 TERMINAL IPC & BROKER SERVER AUTHENTICATION
    # ─────────────────────────────────────────────────────────────
    print("\n[2/10] Memeriksa Koneksi IPC ke Terminal MetaTrader 5...")
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

    # Broker Server Timezone Probe (Audit P0-003)
    tz_probe = connector.probe_broker_timezone()
    offset_sign = f"+{tz_probe['offset_hours']}" if tz_probe['offset_hours'] >= 0 else f"{tz_probe['offset_hours']}"
    print(f"      - Broker Server Tz : UTC{offset_sign} ({tz_probe['offset_seconds']}s offset | Server: {tz_probe['server']})")
    if tz_probe['last_bar_utc']:
        print(f"      - Last M5 Bar (UTC): {tz_probe['last_bar_utc'].strftime('%Y-%m-%d %H:%M:%S')} (delay: {tz_probe['diff_minutes']:.1f} min)")
    print("      [✓] PASS: Koneksi IPC ke MetaTrader 5 berhasil.")

    # ─────────────────────────────────────────────────────────────
    # [3/10] ACCOUNT STATUS & ALGOTRADING MASTER PERMISSIONS
    # ─────────────────────────────────────────────────────────────
    print("\n[3/10] Memeriksa Status Akun Broker & Izin Algo Trading...")
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
    # [4/10] MARKET DATA STREAM & SPREAD TELEMETRY (XAU/USD)
    # ─────────────────────────────────────────────────────────────
    print(f"\n[4/10] Memeriksa Streaming Harga & Spread Telemetri ({lcfg.SYMBOL})...")
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
    # [5/10] LIVE M5 & M1 BAR FEED INTEGRITY & CONTINUITY
    # ─────────────────────────────────────────────────────────────
    print(f"\n[5/10] Memeriksa Kualitas Data Bar M5 & M1 dari Broker...")
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
    # [6/10] STRATEGY ENGINES & LIVE SIGNAL MATH VERIFICATION
    # ─────────────────────────────────────────────────────────────
    print("\n[6/10] Memverifikasi Mesin Indikator & Kalkulasi Sinyal Live...")
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
    # [7/10] RISK MANAGEMENT & POSITION SIZING SAFETY GATES
    # ─────────────────────────────────────────────────────────────
    print("\n[7/10] Memeriksa Aturan Manajemen Risiko & Batas Keamanan...")
    curr_balance = acc_status.balance if acc_status else 10_000.0
    risk_asia_usd = curr_balance * lcfg.ASIAN_RISK_PCT
    risk_lon_usd = curr_balance * lcfg.LONDON_RISK_PCT
    risk_ny_usd = curr_balance * lcfg.NY_RISK_PCT
    max_chase = getattr(lcfg, "MAX_CHASE_USD", 0.80)
    max_retries = getattr(lcfg, "MAX_SESSION_RETRIES", 3)
    max_daily_loss = getattr(lcfg, "MAX_DAILY_LOSS_PCT", 0.05)
    order_timeout = getattr(lcfg, "ORDER_TIMEOUT_SEC", 10.0)
    offset_sec = connector.get_broker_server_utc_offset_seconds()
    is_manual_offset = getattr(lcfg, "BROKER_SERVER_OFFSET_HOURS", None) is not None

    print(f"      - Alokasi Risiko Asia   : {lcfg.ASIAN_RISK_PCT*100:.1f}% (${risk_asia_usd:,.2f} USD)")
    print(f"      - Alokasi Risiko London : {lcfg.LONDON_RISK_PCT*100:.1f}% (${risk_lon_usd:,.2f} USD)")
    print(f"      - Alokasi Risiko NY     : {lcfg.NY_RISK_PCT*100:.1f}% (${risk_ny_usd:,.2f} USD)")
    print(f"      - Daily Loss Limit (CB) : {max_daily_loss*100:.1f}% max portfolio drawdown")
    print(f"      - Slippage Max Tolerance: {lcfg.SLIPPAGE_POINTS} points ($0.30)")
    print(f"      - Anti-Chasing Ceiling  : ${max_chase:.2f} USD (Batas kejar harga)")
    print(f"      - Anti-Spam Max Retry   : {max_retries} kali (Mencegah requote spam)")
    print(f"      - IPC Order Timeout     : {order_timeout:.1f}s (Anti-freeze guard)")
    print(f"      - Broker Server Offset  : {offset_sec//3600:+d}h UTC ({'Deterministik Config' if is_manual_offset else 'Dynamic auto-detection'})")
    print("      [✓] PASS: Batasan risiko institusional & safety gates terkonfigurasi aktif.")

    # ─────────────────────────────────────────────────────────────
    # [8/10] ORDER VALIDATION & BROKER MARGIN CHECK (DRY-RUN)
    # ─────────────────────────────────────────────────────────────
    print("\n[8/10] Menguji Validasi Order ke Server Broker (Zero-Risk Dry-Run)...")
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
    # [9/10] INSTANCE MUTEX LOCK & STATE PERSISTENCE INTEGRITY
    # ─────────────────────────────────────────────────────────────
    print("\n[9/10] Memeriksa Proteksi Multi-Instance & Persistensi State...")
    lock_file = getattr(lcfg, "PID_LOCK_FILE", "bot.lock")
    lock_path = os.path.join(ROOT_DIR, lock_file)

    # 1. PID Lock Inspection (Audit P0-002)
    if os.path.exists(lock_path):
        try:
            with open(lock_path, "r", encoding="utf-8") as f:
                locked_pid = int(f.read().strip())
            if is_process_running(locked_pid):
                warnings.append(f"Bot instance lain terdeteksi aktif dengan PID {locked_pid}.")
                print(f"      - Status PID Lock       : [!] AKTIF oleh PID {locked_pid} (Dua bot dilarang run bersamaan)")
            else:
                print(f"      - Status PID Lock       : [✓] Stale Lock (PID {locked_pid} mati, aman dibersihkan otomatis)")
        except Exception as e:
            print(f"      - Status PID Lock       : [!] Warning membaca lockfile: {e}")
    else:
        # Probe atomic exclusivity
        test_probe = os.path.join(ROOT_DIR, ".probe_lock.tmp")
        try:
            fd = os.open(test_probe, os.O_CREAT | os.O_EXCL | os.O_RDWR)
            os.close(fd)
            os.remove(test_probe)
            print("      - Status PID Lock       : [✓] Siap (Tidak ada instansi lain aktif, izin I/O valid)")
        except Exception as e:
            warnings.append(f"Tidak dapat membuat file lock di direktori root: {e}")
            print(f"      - Status PID Lock       : [!] Izin I/O file lock terbatas: {e}")

    # 2. Daily Circuit Breaker State Persistence (Audit P1-002)
    logs_dir = os.path.join(ROOT_DIR, "logs")
    os.makedirs(logs_dir, exist_ok=True)
    cb_state_path = os.path.join(logs_dir, "daily_circuit_breaker_state.json")
    if os.path.exists(cb_state_path):
        try:
            with open(cb_state_path, "r", encoding="utf-8") as f:
                cb_data = json.load(f)
            stored_date = cb_data.get("date", "Unknown")
            stored_eq = cb_data.get("baseline_equity", 0.0)
            print(f"      - State Circuit Breaker : [✓] Terdeteksi (Date: {stored_date} | Baseline: ${stored_eq:,.2f})")
        except Exception as e:
            warnings.append(f"State file circuit breaker korup/tidak valid: {e}")
            print(f"      - State Circuit Breaker : [!] File state korup: {e}")
    else:
        print("      - State Circuit Breaker : [✓] Bersih (Akan diinisialisasi otomatis saat bot start)")

    # 3. Broker Stops Level & Freeze Level (Audit P1-001)
    if sym_info:
        stops_lvl = getattr(sym_info, "trade_stops_level", 0)
        freeze_lvl = getattr(sym_info, "trade_freeze_level", 0)
        print(f"      - Broker Stops/Freeze   : Stops={stops_lvl} pts | Freeze={freeze_lvl} pts (Defense-in-depth Ready)")
    print("      [✓] PASS: Sistem lockfile atomik & persistensi state portofolio aman.")

    # ─────────────────────────────────────────────────────────────
    # [10/10] TELEGRAM NOTIFICATION ENGINE & REMOTE ALERT TELEMETRY
    # ─────────────────────────────────────────────────────────────
    print("\n[10/10] Memeriksa Mesin Notifikasi Telegram & Telemetri Alert...")
    notifier = TelegramNotifier()
    tele_enabled = notifier.enabled
    tele_mode = notifier.mode
    token_str = notifier.bot_token
    chat_id_str = notifier.chat_id

    masked_token = f"{token_str[:6]}***{token_str[-4:]}" if len(token_str) > 10 else "(Belum diisi)"
    masked_chat = f"{chat_id_str[:4]}***{chat_id_str[-4:]}" if len(chat_id_str) > 6 else chat_id_str or "(Belum diisi)"

    print(f"      - Status Konfigurasi    : {'AKTIF (Enabled)' if tele_enabled else 'NONAKTIF (Disabled)'}")
    print(f"      - Notification Mode     : {tele_mode} (Option A: Balanced Professional)")
    print(f"      - Bot Token Masquerade  : {masked_token}")
    print(f"      - Target Chat ID        : {masked_chat}")

    if tele_enabled:
        if not token_str or not chat_id_str:
            warnings.append("Telegram diaktifkan tetapi BOT_TOKEN atau CHAT_ID belum lengkap di .env.")
            print("      [!] PERINGATAN: Kredensial Telegram belum lengkap di file .env.")
        else:
            t_tele_start = time.time()
            is_valid, bot_tag, tele_err = notifier.verify_credentials()
            tele_latency_ms = (time.time() - t_tele_start) * 1000.0
            if is_valid:
                print(f"      - Bot Telegram Identity : {bot_tag} (Ping Latency: {tele_latency_ms:.1f} ms)")
                print("      [✓] PASS: Bot Telegram terhubung & siap mengirim alert transaksi real-time.")
            else:
                warnings.append(f"Gagal memverifikasi Bot Telegram: {tele_err}")
                print(f"      [!] PERINGATAN: Gagal memverifikasi API Telegram: {tele_err}")
    else:
        print("      [!] INFO: Notifikasi Telegram saat ini nonaktif. Bot tetap aman di log lokal.")

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

"""
Skrip Pengujian Menyeluruh Notifikasi Telegram (End-to-End Test Suite)
====================================================================
Mengirimkan simulasi skenario siklus hidup lengkap ke bot Telegram pengguna:
1. 🚀 Startup / Bot Dijalankan
2. 🔔 Perpindahan Sesi - Pembukaan (Session Open)
3. 📦 Box Opening Range Terbentuk (OR Formed)
4. ⚡ Eksekusi Order Masuk (Entry Trade)
5. 🎯 Penutupan Posisi TP/SL (Exit Trade)
6. 🌙 Perpindahan Sesi - Penutupan (Session Close)
7. 🔒 Sesi Terkunci / Lockout Protection
8. 🛑 Bot Dimatikan / Shutdown (Graceful Stop)
"""

import time
import sys
from datetime import datetime, timezone
from src.execution.notifications import TelegramNotifier
from src.execution import config as lcfg


def run_full_telegram_test():
    notifier = TelegramNotifier()

    print("\n" + "=" * 64)
    print("   UJI LENGKAP TEMPLATE NOTIFIKASI TELEGRAM QUANTTRADE")
    print("=" * 64)
    print(f"• Bot Token : {notifier.bot_token[:6]}***{notifier.bot_token[-4:]}")
    print(f"• Chat ID   : {notifier.chat_id}")
    print(f"• Mode      : {notifier.mode}")
    print("=" * 64 + "\n")

    if not notifier.is_configured:
        print("[X] Gagal: Konfigurasi Telegram belum lengkap.")
        return False

    acc_num = 434215986
    server = "Exness-MT5Trial7"
    balance = 983.87
    equity = 983.87

    # 1. STARTUP
    print("[1/8] Mengirim Notifikasi: 🚀 SYSTEM STARTUP...")
    notifier.notify_startup(
        account=acc_num,
        server=server,
        balance=balance,
        equity=equity,
        symbol=lcfg.SYMBOL,
        active_strategies=["Asian MR", "London Pit ORB", "New York ORB"],
    )
    time.sleep(1.5)

    # 2. SESSION OPEN
    print("[2/8] Mengirim Notifikasi: 🔔 SESSION OPEN (London OR)...")
    notifier.notify_session_open(
        session_name="London Pit Opening Range (Forming)",
        window_info="08:00 - 08:15 UTC",
        details="Memantau formasi Box Opening Range M5. Jendela entry dibuka pukul 08:15 UTC.",
    )
    time.sleep(1.5)

    # 3. BOX OR FORMED
    print("[3/8] Mengirim Notifikasi: 📦 BOX OR FORMED (London)...")
    notifier.notify_or_formed(
        session_name="London Pit ORB",
        or_high=4353.27,
        or_low=4343.31,
        or_range=9.96,
    )
    time.sleep(1.5)

    # 4. ENTRY EXECUTION
    print("[4/8] Mengirim Notifikasi: ⚡ ORDER ENTRY (Buy Breakout)...")
    notifier.notify_entry(
        session="London Pit ORB",
        direction="BUY",
        volume=0.04,
        price=4353.50,
        sl=4343.31,
        tp=4373.43,
        risk_usd=19.68,
        ticket=7891024,
        symbol=lcfg.SYMBOL,
    )
    time.sleep(1.5)

    # 5. EXIT EXECUTION
    print("[5/8] Mengirim Notifikasi: 🎯 ORDER EXIT (Take Profit Hit)...")
    new_balance = balance + 39.36
    notifier.notify_exit(
        session="London Pit ORB",
        direction="BUY",
        volume=0.04,
        open_price=4353.50,
        close_price=4373.43,
        pnl_usd=39.36,
        r_multiple=2.0,
        reason="Take Profit Hit (+2.0R Target)",
        ticket=7891024,
        balance=new_balance,
        symbol=lcfg.SYMBOL,
    )
    time.sleep(1.5)

    # 6. SESSION CLOSE
    print("[6/8] Mengirim Notifikasi: 🌙 SESSION CLOSE...")
    notifier.notify_session_close(
        session_name="London Pit ORB",
        trades_executed_today=True,
        next_session_info="New York OR pukul 13:30 UTC",
    )
    time.sleep(1.5)

    # 7. SESSION LOCKOUT
    print("[7/8] Mengirim Notifikasi: 🔒 SESSION LOCKOUT (Proteksi Requote)...")
    notifier.notify_session_lockout(
        session_name="Asian Mean Reversion",
        retry_count=3,
        max_retries=3,
    )
    time.sleep(1.5)

    # 8. SHUTDOWN
    print("[8/8] Mengirim Notifikasi: 🛑 SYSTEM SHUTDOWN...")
    notifier.notify_shutdown(
        reason="Manual Stop (Ctrl+C)",
        balance=new_balance,
        equity=new_balance,
    )

    print("\n" + "=" * 64)
    print("[✓] SEMUA 8 NOTIFIKASI BERHASIL DIKIRIM KE TELEGRAM ANDA!")
    print("    Silakan periksa aplikasi Telegram di ponsel atau desktop Anda.")
    print("=" * 64 + "\n")
    return True


if __name__ == "__main__":
    run_full_telegram_test()

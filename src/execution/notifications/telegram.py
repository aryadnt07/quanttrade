"""
Telegram Notification Engine — Institutional Balanced Mode (Option A)
====================================================================
Modul pengiriman notifikasi terpadu ke Telegram via HTTP API resmi.
Didesain untuk ketenangan mental trader (Option A: Balanced Professional Mode):
- [✓] Transparansi eksekusi: hanya kirim ENTRY dan EXIT (tanpa spam floating PnL).
- [✓] Heartbeat harian: 1x sehari jam 00:00 UTC untuk verifikasi kesehatan VPS.
- [✓] Alert kritis teknis: jika MT5 disconnect, saldo kurang, atau exception.
- [✓] Non-blocking & Fail-safe: error pengiriman tidak pernah mengganggu loop trading.
- [✓] Zero-dependency: menggunakan pustaka standar Python (urllib.request).
"""

import os
import sys
import ssl
import json
import urllib.request
import urllib.parse
from datetime import datetime, timezone
from typing import Optional, Dict, Any, Tuple

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from src.execution import config as lcfg


def _create_robust_ssl_context() -> Optional[ssl.SSLContext]:
    """
    Menyediakan SSL Context yang tangguh di lingkungan Windows Server / VPS
    yang mungkin kekurangan sertifikat Root CA atau berada di balik self-signed proxy.
    """
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        pass
    try:
        ctx = ssl.create_default_context()
        return ctx
    except Exception:
        pass
    try:
        return ssl._create_unverified_context()
    except Exception:
        return None


class TelegramNotifier:
    """Mesin pengirim notifikasi Telegram untuk Live Bot."""

    def __init__(
        self,
        bot_token: Optional[str] = None,
        chat_id: Optional[str] = None,
        enabled: Optional[bool] = None,
        mode: Optional[str] = None,
    ):
        self.bot_token = (bot_token or getattr(lcfg, "TELEGRAM_BOT_TOKEN", "")).strip()
        self.chat_id = str(chat_id or getattr(lcfg, "TELEGRAM_CHAT_ID", "")).strip()
        self.enabled = enabled if enabled is not None else getattr(lcfg, "TELEGRAM_ENABLED", False)
        self.mode = (mode or getattr(lcfg, "TELEGRAM_NOTIFY_MODE", "BALANCED")).upper()

    @property
    def is_configured(self) -> bool:
        """Cek apakah kredensial Telegram sudah terisi dan aktif."""
        return self.enabled and bool(self.bot_token) and bool(self.chat_id) and (self.mode != "OFF")

    def verify_credentials(self) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Verifikasi keabsahan Bot Token langsung ke endpoint resmi Telegram (getMe)
        tanpa mengirimkan pesan spam ke ruang obrolan (chat).

        Returns:
            Tuple (is_valid, bot_username, error_message)
        """
        if not self.bot_token:
            return False, None, "Bot token kosong"
        url = f"https://api.telegram.org/bot{self.bot_token}/getMe"
        req = urllib.request.Request(url, method="GET")
        ctx = _create_robust_ssl_context()

        try:
            with urllib.request.urlopen(req, timeout=6.0, context=ctx) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode("utf-8"))
                    if data.get("ok"):
                        res = data.get("result", {})
                        username = res.get("username", "")
                        first_name = res.get("first_name", "")
                        tag = f"@{username}" if username else first_name
                        return True, tag, None
                    return False, None, f"Telegram API error: {data.get('description', 'Unknown')}"
                return False, None, f"HTTP Error status {resp.status}"
        except Exception as e:
            # Toleransi jika Windows Server memblokir verifikasi sertifikat SSL
            if "CERTIFICATE_VERIFY_FAILED" in str(e):
                try:
                    unverified_ctx = ssl._create_unverified_context()
                    with urllib.request.urlopen(req, timeout=6.0, context=unverified_ctx) as resp:
                        if resp.status == 200:
                            data = json.loads(resp.read().decode("utf-8"))
                            if data.get("ok"):
                                res = data.get("result", {})
                                username = res.get("username", "")
                                first_name = res.get("first_name", "")
                                tag = f"@{username}" if username else first_name
                                return True, tag, None
                except Exception as inner_e:
                    return False, None, str(inner_e)
            return False, None, str(e)

    def send_message(self, text: str) -> bool:
        """Kirim pesan teks berformat HTML ke Telegram secara aman (fail-safe)."""
        if not self.is_configured:
            return False

        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )
        ctx = _create_robust_ssl_context()

        try:
            with urllib.request.urlopen(req, timeout=6.0, context=ctx) as resp:
                if resp.status == 200:
                    return True
                return False
        except Exception as e:
            if "CERTIFICATE_VERIFY_FAILED" in str(e):
                try:
                    unverified_ctx = ssl._create_unverified_context()
                    with urllib.request.urlopen(req, timeout=6.0, context=unverified_ctx) as resp:
                        return resp.status == 200
                except Exception:
                    pass
            print(f"[⚠️ TELEGRAM WARNING] Gagal mengirim pesan ke Telegram: {e}")
            return False

    # ─────────────────────────────────────────────────────────────
    # TEMPLATE NOTIFIKASI BALANCED PROFESSIONAL (OPTION A)
    # ─────────────────────────────────────────────────────────────
    def notify_entry(
        self,
        session: str,
        direction: str,
        volume: float,
        price: float,
        sl: Optional[float],
        tp: Optional[float],
        risk_usd: float,
        ticket: int,
        symbol: str = lcfg.SYMBOL,
    ) -> bool:
        """Kirim notifikasi saat posisi trading resmi dibuka di server broker."""
        if self.mode == "ZEN":
            return False  # Zen mode melarang notifikasi real-time saat entry

        sl_str = f"{sl:.2f}" if sl else "None"
        tp_str = f"{tp:.2f}" if tp else "None"
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

        msg = (
            f"<b>⚡ [EXECUTION] {session}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"• <b>Action:</b> <code>{direction.upper()} {volume:.2f} lot {symbol}</code>\n"
            f"• <b>Fill Price:</b> <code>{price:.2f}</code>\n"
            f"• <b>Risk Budget:</b> <code>${risk_usd:.2f} USD</code>\n"
            f"• <b>Stop Loss:</b> <code>{sl_str}</code>\n"
            f"• <b>Take Profit:</b> <code>{tp_str}</code>\n"
            f"• <b>Order Ticket:</b> <code>#{ticket}</code>\n"
            f"• <b>Compliance:</b> Institutional Rule Passed\n"
            f"• <b>Timestamp:</b> <code>{now_str}</code>"
        )
        return self.send_message(msg)

    def notify_exit(
        self,
        session: str,
        direction: str,
        volume: float,
        open_price: float,
        close_price: float,
        pnl_usd: float,
        r_multiple: float,
        reason: str,
        ticket: int,
        balance: float,
        symbol: str = lcfg.SYMBOL,
    ) -> bool:
        """Kirim notifikasi saat posisi selesai ditutup (TP / SL / Cutoff)."""
        pnl_sign = "+" if pnl_usd >= 0 else ""
        r_sign = "+" if r_multiple >= 0 else ""
        icon = "🎯" if pnl_usd > 0 else ("🛑" if pnl_usd < 0 else "⚖️")
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

        msg = (
            f"<b>{icon} [CLOSED] {session}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"• <b>Ticket:</b> <code>#{ticket}</code> ({direction} {volume:.2f} lot {symbol})\n"
            f"• <b>Exit Reason:</b> <code>{reason}</code>\n"
            f"• <b>Price Flow:</b> <code>{open_price:.2f}</code> ➔ <code>{close_price:.2f}</code>\n"
            f"• <b>Net PnL:</b> <b><code>{pnl_sign}${pnl_usd:.2f} USD</code></b> (<code>{r_sign}{r_multiple:.2f}R</code>)\n"
            f"• <b>Account Balance:</b> <code>${balance:,.2f} USD</code>\n"
            f"• <b>Portfolio State:</b> Flat (Awaiting Next Session)\n"
            f"• <b>Timestamp:</b> <code>{now_str}</code>"
        )
        return self.send_message(msg)

    def notify_daily_heartbeat(
        self,
        balance: float,
        equity: float,
        free_margin: float,
        server: str,
        latency_ms: float,
        next_session: str,
    ) -> bool:
        """Kirim laporan status harian (Daily Heartbeat) 1x sehari jam 00:00 UTC."""
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

        msg = (
            f"<b>🛡️ [HEARTBEAT] QuantTrade 24/7 Engine</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"• <b>System Status:</b> <code>ONLINE &amp; OPERATIONAL</code>\n"
            f"• <b>MT5 Broker Server:</b> <code>{server}</code>\n"
            f"• <b>IPC Ping Latency:</b> <code>{latency_ms:.1f} ms</code>\n"
            f"• <b>Current Balance:</b> <code>${balance:,.2f} USD</code>\n"
            f"• <b>Current Equity:</b> <code>${equity:,.2f} USD</code>\n"
            f"• <b>Free Margin:</b> <code>${free_margin:,.2f} USD</code>\n"
            f"• <b>Next Scheduled Session:</b> <code>{next_session}</code>\n"
            f"• <b>UTC Timestamp:</b> <code>{now_str}</code>"
        )
        return self.send_message(msg)

    def notify_critical_alert(self, title: str, details: str) -> bool:
        """Kirim alert mendesak jika terjadi kegagalan infrastruktur / teknis."""
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

        msg = (
            f"<b>⚠️ [CRITICAL ALERT] {title}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"• <b>Details:</b> <code>{details}</code>\n"
            f"• <b>Required Action:</b> Silakan periksa terminal VPS / koneksi broker Anda.\n"
            f"• <b>Timestamp:</b> <code>{now_str}</code>"
        )
        return self.send_message(msg)

    def notify_startup(
        self,
        account: int,
        server: str,
        balance: float,
        equity: float,
        symbol: str = lcfg.SYMBOL,
        active_strategies: Optional[list] = None,
    ) -> bool:
        """Kirim notifikasi saat bot live berhasil diinisialisasi dan mulai aktif."""
        strats_str = ", ".join(active_strategies) if active_strategies else "Asian MR, London ORB, NY ORB"
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

        msg = (
            f"<b>🚀 [SYSTEM STARTUP] QuantTrade 24/7 Engine</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"Bot live execution telah <b>AKTIF</b> di Windows VPS/Terminal.\n"
            f"• <b>Akun MT5:</b> <code>{account} ({server})</code>\n"
            f"• <b>Saldo:</b> <code>${balance:,.2f} USD</code>\n"
            f"• <b>Ekuitas:</b> <code>${equity:,.2f} USD</code>\n"
            f"• <b>Simbol:</b> <code>{symbol}</code>\n"
            f"• <b>Mode Notifikasi:</b> <code>{self.mode}</code>\n"
            f"• <b>Strategi Aktif:</b> <code>{strats_str}</code>\n"
            f"• <b>Status:</b> <code>Monitoring Real-Time Ticks</code>\n"
            f"• <b>Waktu Mulai:</b> <code>{now_str}</code>"
        )
        return self.send_message(msg)

    def notify_shutdown(
        self,
        reason: str = "Manual Stop (Ctrl+C)",
        balance: Optional[float] = None,
        equity: Optional[float] = None,
    ) -> bool:
        """Kirim notifikasi saat bot dimatikan / berhenti beroperasi."""
        bal_str = f"${balance:,.2f} USD" if balance is not None else "N/A"
        eq_str = f"${equity:,.2f} USD" if equity is not None else "N/A"
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

        msg = (
            f"<b>🛑 [SYSTEM SHUTDOWN] QuantTrade Engine Berhenti</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"Bot live execution telah <b>DIMATIKAN / OFFLINE</b>.\n"
            f"• <b>Alasan:</b> <code>{reason}</code>\n"
            f"• <b>Saldo Terakhir:</b> <code>{bal_str}</code>\n"
            f"• <b>Ekuitas Terakhir:</b> <code>{eq_str}</code>\n"
            f"• <b>Koneksi MT5:</b> Ditutup dengan aman\n"
            f"• <b>PID Lock:</b> Dirilis\n"
            f"• <b>Waktu Berhenti:</b> <code>{now_str}</code>"
        )
        return self.send_message(msg)

    def notify_session_open(
        self,
        session_name: str,
        window_info: str,
        details: str = "",
    ) -> bool:
        """Kirim notifikasi saat sesi trading resmi dimulai."""
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

        msg = (
            f"<b>🔔 [SESSION OPEN] {session_name}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"• <b>Jendela Waktu:</b> <code>{window_info}</code>\n"
            f"• <b>Status:</b> <code>AKTIF (Mencari Peluang Entri)</code>\n"
            + (f"• <b>Info:</b> {details}\n" if details else "")
            + f"• <b>Waktu:</b> <code>{now_str}</code>"
        )
        return self.send_message(msg)

    def notify_session_close(
        self,
        session_name: str,
        trades_executed_today: bool = False,
        next_session_info: str = "",
    ) -> bool:
        """Kirim notifikasi saat sesi trading berakhir."""
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        trade_status = "Eksekusi Dilakukan" if trades_executed_today else "Tidak Ada Trade / Flat"

        msg = (
            f"<b>🌙 [SESSION CLOSE] {session_name}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"• <b>Status:</b> Sesi telah ditutup (Cutoff / Window Ended)\n"
            f"• <b>Hasil Sesi:</b> <code>{trade_status}</code>\n"
            + (f"• <b>Sesi Berikutnya:</b> <code>{next_session_info}</code>\n" if next_session_info else "")
            + f"• <b>Waktu:</b> <code>{now_str}</code>"
        )
        return self.send_message(msg)

    def notify_or_formed(
        self,
        session_name: str,
        or_high: float,
        or_low: float,
        or_range: float,
    ) -> bool:
        """Kirim notifikasi saat box Opening Range selesai terbentuk."""
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

        msg = (
            f"<b>📦 [BOX OR FORMED] {session_name}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"Opening Range M5 telah terkunci dan siap untuk breakout!\n"
            f"• <b>Range High:</b> <code>{or_high:.2f}</code>\n"
            f"• <b>Range Low:</b> <code>{or_low:.2f}</code>\n"
            f"• <b>Total Range:</b> <code>{or_range:.2f} pts (${or_range:.2f})</code>\n"
            f"• <b>Waktu Terbentuk:</b> <code>{now_str}</code>"
        )
        return self.send_message(msg)

    def notify_session_lockout(
        self,
        session_name: str,
        retry_count: int,
        max_retries: int,
    ) -> bool:
        """Kirim notifikasi jika sesi dilockout karena requote spam protection."""
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

        msg = (
            f"<b>🔒 [SESSION LOCKOUT] {session_name}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"• <b>Penyebab:</b> Percobaan order gagal melampaui batas ({retry_count}/{max_retries}x)\n"
            f"• <b>Aksi Bot:</b> Sesi {session_name} dikunci hari ini untuk keamanan modal.\n"
            f"• <b>Waktu:</b> <code>{now_str}</code>"
        )
        return self.send_message(msg)



def test_telegram_connection() -> bool:
    """Fungsi diagnostik mandiri untuk menguji koneksi bot Telegram."""
    notifier = TelegramNotifier()
    print("\n========================================================")
    print("   QUANTTRADE — TELEGRAM BOT CONNECTION TEST")
    print("========================================================")
    print(f"  • Enabled Config : {notifier.enabled}")
    print(f"  • Notification   : Mode {notifier.mode}")
    token_preview = f"{notifier.bot_token[:6]}***{notifier.bot_token[-4:]}" if len(notifier.bot_token) > 10 else "(Belum diisi)"
    print(f"  • Bot Token      : {token_preview}")
    print(f"  • Target Chat ID : {notifier.chat_id or '(Belum diisi)'}")

    if not notifier.is_configured:
        print("\n[!] PERINGATAN: Konfigurasi Telegram belum lengkap atau belum aktif.")
        print("    Silakan buka file `.env` (atau `src/execution/config.py`) dan isi:")
        print("    TELEGRAM_ENABLED   = true")
        print("    TELEGRAM_BOT_TOKEN = \"<TOKEN_BOT_ANDA>\"")
        print("    TELEGRAM_CHAT_ID   = \"<CHAT_ID_ANDA>\"")
        print("========================================================\n")
        return False

    print("\n[*] Mengirim pesan uji coba ke Telegram...")
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    test_msg = (
        "<b>🎉 [TEST SUCCESS] QuantTrade Telegram Notifier</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "Integrasi Telegram Bot berhasil terhubung ke sistem live!\n"
        f"• <b>Mode:</b> <code>{notifier.mode} (Option A)</code>\n"
        f"• <b>Status:</b> Ready for VPS 24/7 Deployment\n"
        f"• <b>Test Timestamp:</b> <code>{now_utc}</code>"
    )

    success = notifier.send_message(test_msg)
    if success:
        print("[✓] SUKSES: Pesan uji coba berhasil terkirim ke Telegram Anda!")
        print("    Silakan periksa aplikasi Telegram di ponsel atau desktop Anda.")
    else:
        print("[X] GAGAL: Tidak dapat mengirim pesan. Pastikan Token & Chat ID benar.")
    print("========================================================\n")
    return success


if __name__ == "__main__":
    test_telegram_connection()

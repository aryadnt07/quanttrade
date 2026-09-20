"""
Live Trading Risk Manager & Concurrency Safety
==============================================
Komponen pengaman risiko institusional:
1. Atomic Exclusive PID Single-Instance Lockfile (Point P0-002 Audit)
2. Persistent Daily Loss Circuit Breaker 5% (Point P1-003 & NEW-P1-001 Audit)
3. Broker Order Reconciliation Guard (Point NEW-P0-001 Audit)
4. Anti-Spam / Requote Lockout Guard (Point #2 Audit)
5. In-Flight Order Mutex Lock (Point P0-001 Audit)
"""

import os
import sys
import time
import json
from datetime import datetime, timezone, date
from typing import Optional, Dict, Any

from configs import live_config as lcfg


def is_process_running(pid: int) -> bool:
    """Cek apakah proses dengan PID tertentu masih aktif berjalan di OS (Point P0-002 Audit)."""
    if pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes
        kernel32 = ctypes.windll.kernel32
        SYNCHRONIZE = 0x00100000
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE, False, pid)
        if handle:
            res = kernel32.WaitForSingleObject(handle, 0)
            kernel32.CloseHandle(handle)
            return res == 258  # 258 = STILL_ACTIVE (WAIT_TIMEOUT)
        return False
    else:
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False


class RiskManagementMixin:
    """Mixin pengelola risiko portofolio live, state persistence, dan penguncian instance."""

    def _acquire_pid_lock(self) -> bool:
        """
        Kunci instance bot dengan PID lockfile eksklusif atomik (Point P0-002 Adversarial Audit).
        Mencegah dua instance bot berjalan bersamaan di VPS.
        """
        lock_file = getattr(lcfg, "PID_LOCK_FILE", "bot.lock")
        current_pid = os.getpid()

        # Mendukung dynamic patch pada live.live_runner.is_process_running (untuk unit tests)
        lr_mod = sys.modules.get("live.live_runner")
        running_checker = getattr(lr_mod, "is_process_running", is_process_running)

        if os.path.exists(lock_file):
            try:
                with open(lock_file, "r") as f:
                    content = f.read().strip()
                if content:
                    existing_pid = int(content)
                    if running_checker(existing_pid) and existing_pid != current_pid:
                        err_msg = (
                            "\n" + "!" * 76 + "\n"
                            f"  [💥 DUAL INSTANCE DETECTED] Instance bot lain sedang aktif dengan PID {existing_pid}!\n"
                            f"  Dua bot dilarang berjalan bersamaan untuk mencegah duplicate orders (P0-002).\n"
                            f"  Jika ingin merestart, hentikan proses PID {existing_pid} terlebih dahulu.\n"
                            "!" * 76 + "\n"
                        )
                        print(err_msg)
                        self.logger.critical(f"[💥 DUAL INSTANCE BLOCKED] Bot lain dengan PID {existing_pid} sedang aktif.")
                        return False
                    else:
                        self.logger.warning(f"[⚠️ STALE LOCK DETECTED] Lockfile lama ditemukan (PID {existing_pid} tidak aktif). Menghapus stale lockfile...")
                        try:
                            os.remove(lock_file)
                        except OSError as err:
                            self.logger.critical(f"[💥 CANNOT REMOVE STALE LOCK] Gagal menghapus stale lock: {err}. Bot berhenti (Fail-Closed).")
                            return False
            except (ValueError, IOError) as e:
                self.logger.warning(f"[⚠️ LOCKFILE READ ERROR] Gagal membaca lockfile ({e}). Mencoba menghapus...")
                try:
                    os.remove(lock_file)
                except OSError as err:
                    self.logger.critical(f"[💥 CANNOT REMOVE CORRUPT LOCK] Gagal menghapus corrupt lock: {err}. Bot berhenti (Fail-Closed).")
                    return False

        try:
            # Mode 'x' = Exclusive Creation (O_CREAT | O_EXCL di level OS kernel)
            with open(lock_file, "x") as f:
                f.write(str(current_pid))
            self._lock_acquired = True
            self.logger.info(f"[🔒 PID LOCK ACQUIRED] Bot instance terkunci atomik dengan PID {current_pid} ({lock_file}).")
            return True
        except FileExistsError:
            self.logger.critical("[💥 DUAL INSTANCE RACE DETECTED] Lockfile baru saja dibuat oleh proses lain. Eksekusi dibatalkan (Fail-Closed).")
            return False
        except Exception as e:
            self.logger.critical(f"[💥 LOCK ACQUIRE FAILED] Gagal membuat PID lockfile: {e}. Bot berhenti (Fail-Closed).")
            return False

    def _release_pid_lock(self):
        """Hapus lockfile saat bot berhenti dengan aman."""
        if getattr(self, "_lock_acquired", False):
            lock_file = getattr(lcfg, "PID_LOCK_FILE", "bot.lock")
            try:
                if os.path.exists(lock_file):
                    with open(lock_file, "r") as f:
                        content = f.read().strip()
                    if content and int(content) == os.getpid():
                        os.remove(lock_file)
                        self.logger.info(f"[🔓 PID LOCK RELEASED] Lockfile {lock_file} berhasil dibersihkan.")
            except Exception as e:
                self.logger.warning(f"[!] Gagal membersihkan lockfile: {e}")
            self._lock_acquired = False

    def _get_daily_state_path(self) -> str:
        """Lokasi file JSON persistensi baseline ekuitas harian."""
        log_dir = getattr(lcfg, "LOG_DIR", "logs")
        os.makedirs(log_dir, exist_ok=True)
        return os.path.join(log_dir, "daily_circuit_breaker_state.json")

    def _save_daily_circuit_breaker_state(self, current_trading_day: Optional[date] = None):
        """Simpan baseline modal harian ke file JSON."""
        try:
            path = self._get_daily_state_path()
            target_day = current_trading_day or getattr(self, "current_trading_day", None)
            data = {
                "date": target_day.isoformat() if target_day else "",
                "starting_equity": self.starting_daily_equity,
                "circuit_breaker_tripped": self.daily_circuit_breaker_tripped,
            }
            with open(path, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            self.logger.warning(f"[!] Gagal menyimpan daily circuit breaker state: {e}")

    def _load_or_init_daily_circuit_breaker(self, today_date: date):
        """
        Inisialisasi baseline ekuitas harian dengan persistensi dan rekonsiliasi riwayat deal MT5 (NEW-P1-001).
        Mencegah reset limit drawdown harian saat bot crash/restart di tengah sesi.
        """
        path = self._get_daily_state_path()
        loaded = False

        if os.path.exists(path):
            try:
                with open(path, "r") as f:
                    data = json.load(f)
                if data.get("date") == today_date.isoformat() and data.get("starting_equity"):
                    self.starting_daily_equity = float(data["starting_equity"])
                    self.daily_circuit_breaker_tripped = bool(data.get("circuit_breaker_tripped", False))
                    loaded = True
                    self.logger.info(f"[*] Daily State Restored -> Baseline Equity: ${self.starting_daily_equity:,.2f} | CB Tripped: {self.daily_circuit_breaker_tripped}")
                    if self.daily_circuit_breaker_tripped:
                        self.trades_today["ASIAN"] = True
                        self.trades_today["LONDON"] = True
                        self.trades_today["NY"] = True
            except Exception as e:
                self.logger.warning(f"[!] Gagal membaca daily state file: {e}")

        if not loaded:
            acc = self.connector.get_account_status()
            if not acc or acc.equity <= 0:
                self.logger.critical("[💥 EQUITY FETCH FAILED] Gagal membaca status akun MT5 saat inisialisasi Daily Circuit Breaker. Bot berhenti (Fail-Closed).")
                raise RuntimeError("Account equity is unavailable from MT5. Aborting bot to protect capital.")

            curr_equity = acc.equity
            today_deals = self.connector.get_today_deals(lcfg.MAGIC_NUMBER)
            today_realized_pnl = sum(d.profit for d in today_deals if hasattr(d, "profit"))
            open_pos = self.connector.get_open_positions(lcfg.MAGIC_NUMBER)
            current_floating = sum(p.profit for p in open_pos if hasattr(p, "profit"))

            # Inferred baseline equity = ekuitas saat ini - PnL hari ini
            inferred_start_equity = curr_equity - today_realized_pnl - current_floating
            if inferred_start_equity <= 0:
                self.logger.warning(f"[⚠️ INFERRED EQUITY ANOMALY] Inferred start equity (${inferred_start_equity:.2f}) <= 0. Menggunakan current equity (${curr_equity:.2f}) sebagai baseline.")
                self.starting_daily_equity = curr_equity
            else:
                self.starting_daily_equity = inferred_start_equity

            self.daily_circuit_breaker_tripped = False
            self._save_daily_circuit_breaker_state(today_date)
            self.logger.info(f"[*] Daily State Initialized -> Baseline Equity: ${self.starting_daily_equity:,.2f} (Inferred from Deals PnL: ${today_realized_pnl:+.2f})")

    def _reconcile_broker_orders(self, session: str) -> bool:
        """
        Cek apakah broker sebenarnya sudah mengisi order sesi ini (NEW-P0-001).
        Mencegah double-order jika order_send timeout tapi order sebenarnya tereksekusi di broker.
        Returns True jika order/deal sudah ada di server broker.
        """
        comm_keyword = "AsiaMR" if session == "ASIAN" else ("London" if session == "LONDON" else "NY")

        # 1. Cek posisi terbuka di broker
        open_pos = self.connector.get_open_positions(lcfg.MAGIC_NUMBER)
        for p in open_pos:
            comm = p.comment or ""
            if comm_keyword in comm:
                self.logger.warning(f"[🛡️ RECONCILIATION MATCH] Posisi {session} (Ticket {p.ticket}) sudah aktif di broker! Membatalkan retry duplicate.")
                self.trades_today[session] = True
                self.retry_counts[session] = 0
                return True

        # 2. Cek riwayat deal hari ini di broker
        today_deals = self.connector.get_today_deals(lcfg.MAGIC_NUMBER)
        for d in today_deals:
            comm = d.comment or ""
            if comm_keyword in comm:
                self.logger.warning(f"[🛡️ RECONCILIATION MATCH] Deal {session} (Ticket {d.ticket}) sudah tercatat di history broker! Membatalkan retry duplicate.")
                self.trades_today[session] = True
                self.retry_counts[session] = 0
                return True

        return False

    def _check_daily_circuit_breaker(self, current_equity: float, today_date: Optional[date] = None) -> bool:
        """Evaluasi apakah drawdown harian portofolio melampaui 5%."""
        if self.starting_daily_equity is None or self.starting_daily_equity <= 0:
            self.starting_daily_equity = current_equity

        daily_drawdown_pct = (self.starting_daily_equity - current_equity) / self.starting_daily_equity
        max_daily_loss = getattr(lcfg, "MAX_DAILY_LOSS_PCT", 0.05)

        if daily_drawdown_pct >= max_daily_loss:
            if not self.daily_circuit_breaker_tripped:
                self.daily_circuit_breaker_tripped = True
                self._save_daily_circuit_breaker_state(today_date)
                msg = (
                    f"[🛑 DAILY CIRCUIT BREAKER ACTIVATED] Daily Drawdown {daily_drawdown_pct*100:.2f}% "
                    f">= limit {max_daily_loss*100:.1f}%! "
                    f"Starting Equity: ${self.starting_daily_equity:,.2f} | Current: ${current_equity:,.2f}. "
                    f"Trading dihentikan untuk sisa hari ini."
                )
                self.logger.critical(msg)
                self.telegram.notify_critical_alert("Daily Circuit Breaker", msg)
                self.trades_today["ASIAN"] = True
                self.trades_today["LONDON"] = True
                self.trades_today["NY"] = True
            return True
        return False

    def _handle_order_result(self, session: str, res):
        """Kelola hasil pengiriman order dengan proteksi max-retries dan rekonsiliasi broker."""
        if res.success:
            self.logger.info(f"[✓] ORDER {session} BERHASIL! Ticket: {res.order_id} @ {res.price}\n")
            self.trades_today[session] = True
            self.retry_counts[session] = 0
        else:
            # Rekonsiliasi broker sebelum retry: cek apakah order sebenarnya sudah terisi di broker saat timeout (NEW-P0-001)
            if self._reconcile_broker_orders(session):
                return

            self.retry_counts[session] += 1
            self.logger.error(f"[X] ORDER {session} GAGAL ({self.retry_counts[session]}/{lcfg.MAX_SESSION_RETRIES}): {res.comment}")

            if res.retcode == 10027:
                self.logger.warning("[⚠️ AKSI DIPERLUKAN] Tombol 'Algo Trading' di terminal MT5 belum aktif! Silakan klik tombol 'Algo Trading' pada toolbar MT5 agar menjadi hijau.")

            if self.retry_counts[session] >= lcfg.MAX_SESSION_RETRIES:
                self.logger.warning(f"[🔒 SESI DILOCKOUT] Batas maksimal percobaan ({lcfg.MAX_SESSION_RETRIES}x) tercapai. Sesi {session} dikunci hari ini untuk melindungi akun dari requote spamming.")
                self.trades_today[session] = True
            else:
                self.logger.info(f"[*] Menunggu jeda {lcfg.RETRY_COOLDOWN_SEC} detik sebelum retry berikutnya...\n")
                time.sleep(lcfg.RETRY_COOLDOWN_SEC)

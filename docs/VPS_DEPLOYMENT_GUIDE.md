# 🖥️ Panduan Deployment & Operasional Live 24/7 di Windows VPS

Panduan teknis langkah-demi-langkah untuk mendeploy bot kuantitatif **QuantTrade (XAU/USD)** di Windows Server VPS hingga berjalan otomatis 24 jam nonstop dengan sistem 1-Click Update.

---

## 1. Rekomendasi Spesifikasi VPS
* **Sistem Operasi**: Windows Server 2019 atau Windows Server 2022 (64-bit).
* **Hardware**: Minimal 2 vCPU, 4 GB RAM, 40 GB SSD.
* **Lokasi Data Center**: **London (LD4)** atau **Frankfurt/Amsterdam** (agar latency ke trade server Exness hanya **1–3 ms**).
* **Rekomendasi Provider VPS**: ForexVPS.net, FXVM, Contabo (Windows), atau Vultr.

---

## 2. Setup Awal di Windows VPS (Cukup Sekali)

### Langkah 1: Instal MetaTrader 5 (Exness)
1. Buka browser di dalam VPS (Chrome/Edge), download installer MT5 dari broker Exness.
2. Instal MT5 seperti biasa dan login ke akun trading Anda.
3. **PENTING**: Aktifkan fitur otomatisasi di terminal MT5:
   - Klik menu **Tools** $\rightarrow$ **Options** $\rightarrow$ Tab **Expert Advisors**.
   - Centang **"Allow Algo Trading"**.
   - Klik tombol **Algo Trading** di toolbar utama atas hingga icon berwarna **Hijau**.
4. Buka market watch dan pastikan simbol **`XAUUSD`** aktif dan chart M5 terbuka.

### Langkah 2: Instal Python di VPS
1. Download installer Python resmi (rekomendasi Python 3.10 - 3.12 64-bit) dari [python.org](https://www.python.org/downloads/).
2. Saat instalasi, **WAJIB CENTANG**:  
   ☑ **"Add python.exe to PATH"**
3. Klik **Install Now**.
4. Download dan instal Git untuk Windows dari [git-scm.com](https://git-scm.com/).

### Langkah 3: Clone Repositori QuantTrade
Buka PowerShell atau Command Prompt di VPS, jalankan:
```powershell
cd C:\
git clone https://github.com/aryadnt07/quanttrade.git
cd quanttrade
pip install -r requirements.txt
```

### Langkah 4: Buat File `.env` untuk Kredensial Sensitif
Di terminal VPS (atau via File Explorer), salin `.env.example` menjadi `.env`:
```powershell
copy .env.example .env
```
Buka file `.env` dengan Notepad di VPS, lalu sesuaikan nomor akun MT5 dan token Telegram Anda:
```ini
# Kredensial Broker MetaTrader 5
MT5_ACCOUNT_LOGIN=434215986
MT5_ACCOUNT_PASSWORD=
MT5_ACCOUNT_SERVER=Exness-MT5Trial7

# Notifikasi Telegram (Option A: Balanced Mode)
TELEGRAM_ENABLED=true
TELEGRAM_BOT_TOKEN=123456789:ABCdefGhIJKlmNoPQRstuVWXyz
TELEGRAM_CHAT_ID=123456789
TELEGRAM_NOTIFY_MODE=BALANCED
```
> **Keamanan**: File `.env` bersifat privat dan secara otomatis diabaikan oleh Git (`.gitignore`), sehingga token atau password Anda tidak akan pernah bocor ke repository GitHub.

---

## 3. Menjalankan & Menguji Bot di VPS (1-Click Automation)

Di dalam folder `deploy/` (atau bisa Anda buatkan shortcut-nya ke Desktop VPS), Anda memiliki alat otomasi berikut:

### A. Uji Kesiapan & Diagnostik Sistem Menyeluruh (`deploy/TEST_LIVE_SYSTEM.bat`)
* **SANGAT DIREKOMENDASIKAN** dijalankan pertama kali setelah instalasi VPS atau sebelum menghidupkan bot 24 jam.
* Klik 2x file `deploy/TEST_LIVE_SYSTEM.bat`.
* Menjalankan **8 Tahap Diagnostik Institusional**:
  1. *Host Environment & UTC Clock Sync* (validasi Python 64-bit & jam UTC).
  2. *MT5 IPC Handshake & Latency* (mengukur ping ke terminal MT5).
  3. *Broker Account & AlgoTrading Permission* (audit saldo, leverage, margin, izin Algo Trading).
  4. *Live Market Telemetry & Spread* (cek live bid/ask, spread XAU/USD, spesifikasi lot).
  5. *Broker Data Feed Integrity* (uji download bar M5 & M1, cek missing bar / NaN).
  6. *Live Indicator Math Verification* (kalkulasi live Z-score Asian, LORB TR_SMA20, NY ORB).
  7. *Risk Management & Safety Gates* (audit lot size per session, slippage tolerance, anti-chase ceiling, anti-spam retry).
  8. *Broker Order Validation (Zero-Risk Dry-Run)* (mengirim payload order uji coba via `order_check` ke server Exness tanpa membuka posisi riil dan tanpa risiko saldo).
* Jika scorecard menyatakan `OPERASIONAL & SIAP LIVE`, sistem telah terverifikasi 100% siap!

### B. Cek Cepat Koneksi Broker (`deploy/CHECK_CONNECTION.bat`)
* Klik 2x file `deploy/CHECK_CONNECTION.bat` untuk ping cepat 5 detik memeriksa status login dan koneksi MT5.

### C. Menjalankan Bot 24/7 (`deploy/START_LIVE_BOT.bat`)
* Klik 2x file `deploy/START_LIVE_BOT.bat`.
* Bot akan langsung aktif dan otomatis memantau 3 sesi pasar (Asia 01:00 UTC, London 08:15 UTC, NY 13:45 UTC).
* **Tips RDP**: Anda bisa menutup (*minimize* / *close*) jendela Remote Desktop (RDP) kapan saja. Bot akan tetap berjalan di background VPS!

---

## 4. Cara Update Bot dari Laptop ke VPS (1-Click)

Ketika Anda melakukan perbaikan, optimasi formula, atau perubahan strategi di laptop:

1. **Di Laptop Anda**:
   ```bash
   git add .
   git commit -m "update formula strategi"
   git push origin main
   ```

2. **Di VPS**:
   * Cukup **klik 2x file `deploy/UPDATE_LIVE_BOT.bat`**.
   * File ini secara otomatis akan:
     1. Menutup proses bot yang lama dengan aman (*graceful stop*).
     2. Mengambil kode terbaru via `git pull origin main`.
     3. Mengupdate library jika ada versi baru.
     4. Menyalakan kembali bot secara otomatis.
   * **State Recovery Aktif**: Jika saat update ada posisi trading yang sedang floating profit/loss, bot baru akan otomatis mengenali tiket tersebut via Magic Number `888001` tanpa membuka trade duplikat!

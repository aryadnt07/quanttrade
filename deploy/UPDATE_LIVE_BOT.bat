@echo off
cd /d "%~dp0\.."
title QuantTrade - Code Updater
color 0e

echo ================================================================
echo    QUANTTRADE - CODE & STRATEGY UPDATER
echo ================================================================
echo.

echo [1/3] Menghentikan sesi bot yang sedang berjalan...
if exist bot.lock (
    set /p BOT_PID=<bot.lock
    if defined BOT_PID (
        echo [*] Menghentikan proses bot aktif dengan PID %BOT_PID%...
        taskkill /F /PID %BOT_PID% /T >nul 2>&1
        timeout /t 1 >nul
        del /f /q bot.lock >nul 2>&1
    )
)
taskkill /F /FI "WINDOWTITLE eq QuantTrade - Institutional Live Bot*" /T >nul 2>&1
echo [✓] Sesi bot aktif berhasil dihentikan secara aman.
echo.

echo [2/3] Mengambil pembaruan kode terbaru dari GitHub (git pull)...
git stash >nul 2>&1
git pull origin main
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [X] Gagal melakukan git pull! Periksa koneksi internet atau status Git Anda.
    pause
    exit /b %ERRORLEVEL%
)
echo [✓] Kode terbaru berhasil ditarik.
echo.

echo [3/3] Memeriksa dependensi Python...
if exist venv\Scripts\activate.bat (
    call venv\Scripts\activate.bat
) else if exist .venv\Scripts\activate.bat (
    call .venv\Scripts\activate.bat
)
pip install -r requirements.txt --quiet
echo [✓] Dependensi sinkron.
echo.

echo ================================================================
echo [✓] UPDATE SELESAI & SUDAH BERSIH!
echo     Sesi bot lama telah dimatikan dan kode telah ter-update.
echo     (Bot TIDAK di-restart otomatis sesuai preferensi Anda).
echo.
echo     Untuk menyalakan kembali bot kapan saja, silakan jalankan:
echo     deploy\START_LIVE_BOT.bat
echo ================================================================
echo.
pause

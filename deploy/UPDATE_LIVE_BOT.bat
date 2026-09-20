@echo off
cd /d "%~dp0\.."
title QuantTrade - 1-Click Production Auto-Updater
color 0e
echo ================================================================
echo    QUANTTRADE - 1-CLICK PRODUCTION AUTO-UPDATER
echo ================================================================
echo.
echo [1/4] Menghentikan bot yang sedang berjalan...
taskkill /F /FI "WINDOWTITLE eq QuantTrade - Institutional Live Bot*" /T >nul 2>&1

echo [2/4] Mengambil pembaruan terbaru dari GitHub (git pull)...
git stash >nul 2>&1
git pull origin main
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [X] Gagal melakukan git pull. Periksa koneksi internet atau otentikasi Git.
    pause
    exit /b %ERRORLEVEL%
)

echo [3/4] Memeriksa dan memperbarui dependensi Python...
pip install -r requirements.txt --quiet

echo [4/4] Memulai ulang bot secara otomatis...
echo.
echo [✓] Update sukses! Menyalakan kembali Live Trading Bot...
timeout /t 2 >nul
start "QuantTrade - Institutional Live Bot (24/7 Engine)" cmd /k "%~dp0START_LIVE_BOT.bat"

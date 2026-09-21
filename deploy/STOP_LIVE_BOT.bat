@echo off
cd /d "%~dp0\.."
title QuantTrade - Stop Live Bot
color 0c

echo ================================================================
echo    QUANTTRADE - STOP LIVE TRADING BOT
echo ================================================================
echo.

if exist bot.lock (
    set /p BOT_PID=<bot.lock
    if defined BOT_PID (
        echo [*] Menghentikan bot aktif dengan PID %BOT_PID%...
        taskkill /F /PID %BOT_PID% /T >nul 2>&1
        timeout /t 1 >nul
        del /f /q bot.lock >nul 2>&1
    )
)
taskkill /F /FI "WINDOWTITLE eq QuantTrade - Institutional Live Bot*" /T >nul 2>&1
echo [✓] Bot berhasil dimatikan secara aman. Lockfile dibersihkan.
echo.
pause

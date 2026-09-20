@echo off
cd /d "%~dp0\.."
title QuantTrade - Institutional Live Bot (24/7 Engine)
color 0a
echo ================================================================
echo    QUANTTRADE - LIVE AUTOMATED TRADING BOT (24/7)
echo ================================================================
echo.
echo [*] Memulai QuantTrade Live Execution Runner...
python main.py live
echo.
echo ================================================================
echo [!] Bot telah berhenti (Exit Code: %ERRORLEVEL%).
echo     Terminal tetap terbuka agar Anda dapat membaca log di atas.
echo ================================================================
echo.
pause


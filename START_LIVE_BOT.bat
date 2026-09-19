@echo off
title QuantTrade - Institutional Live Bot (24/7 Engine)
color 0a
echo ================================================================
echo    QUANTTRADE - LIVE AUTOMATED TRADING BOT (24/7)
echo ================================================================
echo.
echo [*] Memulai QuantTrade Live Execution Runner...
python main.py live
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [!] Bot berhenti dengan kode error: %ERRORLEVEL%.
    pause
)

@echo off
title QuantTrade - MT5 Connection Diagnostic
color 0b
echo ================================================================
echo    QUANTTRADE - MT5 LIVE CONNECTION HEALTH CHECK
echo ================================================================
echo.
python main.py live --check-only
echo.
pause

@echo off
cd /d "%~dp0\.."
title QuantTrade - Live System Readiness Diagnostic Suite
color 0e
echo ================================================================
echo    QUANTTRADE - LIVE SYSTEM READINESS AND DIAGNOSTIC SUITE
echo    Institutional 10-Stage Pre-Check for Live Execution
echo ================================================================
echo.
python main.py live-check
echo.
pause

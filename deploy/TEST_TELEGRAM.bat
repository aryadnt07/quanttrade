@echo off
cd /d "%~dp0\.."
title QuantTrade - Telegram Notification Diagnostic
color 0b

echo ================================================================
echo    QUANTTRADE - TELEGRAM NOTIFICATION TEST
echo ================================================================
echo.

if exist venv\Scripts\activate.bat (
    call venv\Scripts\activate.bat
) else if exist .venv\Scripts\activate.bat (
    call .venv\Scripts\activate.bat
)

python main.py telegram-test
echo.
pause

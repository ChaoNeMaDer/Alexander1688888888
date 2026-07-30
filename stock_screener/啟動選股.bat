@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo.
echo =============================================
echo   箱波均戰法 — 台股選股程式
echo =============================================
echo.
python main.py
echo.
pause

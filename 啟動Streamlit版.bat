@echo off
chcp 65001 >nul
title 恐懼貪婪指數回測系統 (Streamlit)
echo ========================================================
echo   正在啟動 Streamlit 視覺化回測應用 (app.py)...
echo ========================================================
echo.
cd /d "%~dp0"
streamlit run app.py
pause

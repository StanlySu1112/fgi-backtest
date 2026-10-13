@echo off
chcp 65001 >nul
title 更新恐懼貪婪指數數據
echo ========================================================
echo   正在從 CNN API 與歷史數據更新 FGI 指數...
echo ========================================================
echo.
cd /d "%~dp0"
python create_fgi_dataset.py
pause

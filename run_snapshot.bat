@echo off
chcp 65001 >nul
cd /d %~dp0
python push_snapshot.py
echo.
pause

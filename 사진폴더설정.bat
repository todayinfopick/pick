@echo off
chcp 65001 >nul
cd /d "%~dp0"
".venv\Scripts\python.exe" set_photo_dir.py
pause

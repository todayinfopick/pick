@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist logs mkdir logs
if /i "%~1"=="refresh" (
  ".venv\Scripts\python.exe" refresh_tokens.py >> logs\task.log 2>&1
) else (
  ".venv\Scripts\python.exe" main.py >> logs\task.log 2>&1
)

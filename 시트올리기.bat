@echo off
chcp 65001 >nul
cd /d "%~dp0"
".venv\Scripts\python.exe" -m pip install -q google-auth
".venv\Scripts\python.exe" sheet_upload.py https://docs.google.com/spreadsheets/d/18BVfA22ELRzZE6_fWLRy5Qgi-E1y7aY-n44NDfC2h9o/edit
pause

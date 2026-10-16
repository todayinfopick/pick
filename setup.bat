@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo [1/3] Python 확인 중...
python --version >nul 2>nul || (
  echo Python이 설치되어 있지 않습니다. 사용가이드의 1단계를 먼저 진행하세요.
  pause
  exit /b 1
)
echo [2/3] 프로그램 설치 중... (1~2분)
python -m venv .venv
".venv\Scripts\python.exe" -m pip install --upgrade pip -q
".venv\Scripts\python.exe" -m pip install -r requirements.txt -q
echo [3/3] 설정 파일 준비 중...
if not exist .env copy .env.example .env >nul
if not exist logs mkdir logs
echo.
echo 설치 완료! 이제 .env 파일을 메모장으로 열어 키를 입력하세요.
pause

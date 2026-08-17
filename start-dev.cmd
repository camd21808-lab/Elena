@echo off
setlocal
chcp 65001 >nul
title scan-de dev server
cd /d "%~dp0"

echo === scan-de dev ===

echo [1/4] Dang dong port 8000 + 5173 (neu con treo)...
for /f "tokens=5" %%p in ('netstat -ano ^| findstr /R ":8000 .*LISTENING"') do taskkill /F /PID %%p >nul 2>&1
for /f "tokens=5" %%p in ('netstat -ano ^| findstr /R ":5173 .*LISTENING"') do taskkill /F /PID %%p >nul 2>&1
timeout /t 1 /nobreak >nul

echo [2/4] Khoi dong API (uvicorn :8000)...
set "PYTHONPATH=%cd%"
start "scan-de-api" cmd /c ""%cd%\.venv\Scripts\python.exe" -m uvicorn api.main:app --port 8000 --host 127.0.0.1 > api_server.log 2> api_server_err.log"

echo [3/4] Khoi dong UI (vite :5173, strictPort)...
start "scan-de-ui" cmd /k "cd /d "%cd%\ui" && npm run dev -- --strictPort"

echo [4/4] Xong. UI: http://localhost:5173  (API tren 8000, UI goi qua proxy)
echo Mo browser len dung port 5173 - UI se tu dong chuyen qua proxy toi API.
endlocal

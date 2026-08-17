@echo off
setlocal
set PYTHONPATH=D:\App\scan-de
"D:\App\scan-de\.venv\Scripts\python.exe" "D:\App\scan-de\cli\scan.py" %*
exit /b %ERRORLEVEL%

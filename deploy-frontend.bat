@echo off
REM Deploy frontend to GitHub Pages
REM Usage: deploy-frontend.bat https://your-backend.onrender.com

if "%~1"=="" (
    echo Usage: deploy-frontend.bat BACKEND_URL
    echo Example: deploy-frontend.bat https://elena-api-xxxx.onrender.com
    exit /b 1
)

set VITE_API_BASE=%~1
echo Building with API: %VITE_API_BASE%
cd /d D:\App\scan-de\ui
call npm run build
if errorlevel 1 (
    echo Build failed!
    exit /b 1
)
call npx gh-pages -d dist -t true
if errorlevel 1 (
    echo Deploy failed!
    exit /b 1
)
echo Done! Check: https://camd21808-lab.github.io/Elena/

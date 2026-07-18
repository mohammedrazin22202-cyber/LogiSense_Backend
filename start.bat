@echo off
title LogiSense 360 - Backend API Server
color 0B

echo.
echo  ============================================================
echo    LOGISENSE 360 - Backend API Server
echo  ============================================================
echo.
echo    Serves: REST API + SSE stream on http://localhost:1995
echo    Frontend must be started separately via ..\frontend\start.bat
echo  ============================================================
echo.

:: ── Change to backend directory (ensures relative imports work) ────────────────
cd /d "%~dp0"

:: ── Check Python ─────────────────────────────────────────────────────────────
python --version >nul 2>&1
if errorlevel 1 (
    echo  [ERROR] Python not found.
    echo  Install from https://www.python.org/downloads/
    echo  Make sure to check "Add Python to PATH" during install.
    pause
    exit /b 1
)

:: ── Ensure data directory exists ───────────────────────────────────────────────
if not exist "%~dp0data" (
    echo  Creating data directory...
    mkdir "%~dp0data"
)

:: ── Install dependencies ──────────────────────────────────────────────────────
echo  [1/3] Installing Python dependencies...
python -m pip install flask flask-cors openpyxl pymongo --quiet
if errorlevel 1 (
    echo  [WARNING] Some packages may not have installed cleanly. Continuing...
)
echo        Done.

:: ── Seed database (only if xlsx exists) ──────────────────────────────────────
if exist "%~dp0data\orders_master.xlsx" (
    echo  [2/3] Seeding database from orders_master.xlsx...
    echo         ^(This initialises the SQLite database with your order data^)
    python "%~dp0seed.py"
    if errorlevel 1 (
        echo  [WARNING] Seeding had issues - starting server anyway...
    ) else (
        echo        Done.
    )
) else (
    echo  [2/3] Skipping seed ^(orders_master.xlsx not found in backend\data\^)
    echo         The server will start with existing database data.
)

:: ── Start API server ──────────────────────────────────────────────────────────
echo  [3/3] Starting API server...
echo.
echo  ============================================================
echo    Backend ready at:  http://localhost:1995
echo    API prefix:        http://localhost:1995/api/
echo    SSE stream:        http://localhost:1995/api/stream
echo.
echo    Now start the frontend:  ..\frontend\start.bat
echo  ============================================================
echo.
echo  Press Ctrl+C to stop the server.
echo.

python "%~dp0server.py"

pause

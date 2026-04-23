@echo off
REM ─── Atlas of Australia — God's Eye launcher ──────────────────
REM Double-click this file to start the proxy server, then open
REM http://localhost:8777/ in your browser.
REM Close the console window (or Ctrl+C) to stop the server.

cd /d "%~dp0"

echo.
echo  ┌─────────────────────────────────────────────────┐
echo  │  Atlas of Australia — God's Eye                 │
echo  │  Starting proxy server on http://localhost:8777 │
echo  └─────────────────────────────────────────────────┘
echo.

REM Try `py` (Windows Python launcher) first, then plain `python`.
where py >nul 2>nul
if %ERRORLEVEL%==0 (
  py server.py
) else (
  python server.py
)

echo.
echo Server stopped. Press any key to close this window.
pause >nul

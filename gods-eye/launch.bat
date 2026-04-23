@echo off
REM ─── Atlas of Australia — God's Eye V1.2 ────────────────────
REM Starts the God's Eye proxy server, then opens the dashboard
REM in your default browser. Close this window to stop the server.

cd /d "%~dp0"

echo.
echo  +-------------------------------------------------+
echo  ^|  Atlas of Australia -- God's Eye V1.2            ^|
echo  ^|  Starting server...                              ^|
echo  +-------------------------------------------------+
echo.

REM Start the server in the background, open browser after 3s
start "" /B cmd /c "timeout /t 3 /nobreak >nul && start http://localhost:8777"

REM Run the server (blocks until Ctrl+C or window close)
where py >nul 2>nul
if %ERRORLEVEL%==0 (
  py server.py
) else (
  python server.py
)

echo.
echo Server stopped. Press any key to close.
pause >nul

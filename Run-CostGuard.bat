@echo off
setlocal
title CostGuard - Local Web App
cd /d "%~dp0" || (
    echo Could not open the CostGuard project folder.
    pause
    exit /b 2
)
echo Starting CostGuard in your web browser...
echo Keep this window open while using the web page.
echo Press Ctrl+C here to stop the server.
echo.
py -X utf8 "%~dp0web\server.py"
if errorlevel 1 (
    echo.
    echo The web app could not start. Check that Python 3.11 or newer is installed.
    pause
)
endlocal

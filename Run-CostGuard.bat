@echo off
setlocal
title CostGuard - Azure Cost Check
pushd "%~dp0" || (
    echo Could not open the CostGuard project folder.
    pause
    exit /b 2
)

:menu
cls
echo ============================================================
echo             COSTGUARD - AZURE COST CHECK
echo ============================================================
echo.
echo Check the included sample plan: one VM and one managed disk.
echo No Azure VM or subscription is needed.
echo.
echo   1. Run with a $20 monthly increase limit
echo   2. Run with a $50 monthly increase limit
echo   3. Enter a different monthly increase limit
echo   4. Exit
echo.
choice /c 1234 /n /m "Choose 1, 2, 3, or 4: "
if errorlevel 4 goto done
if errorlevel 3 goto custom
if errorlevel 2 (
    set "budget=50"
    goto run
)
if errorlevel 1 (
    set "budget=20"
    goto run
)
goto done

:custom
echo.
set "budget="
set /p "budget=Enter a non-negative amount, for example 35 or 35.50: "
if errorlevel 1 goto menu
if not defined budget goto invalid
echo(%budget%| findstr /r /c:"^[0-9][0-9]*$" /c:"^[0-9][0-9]*\.[0-9][0-9]*$" >nul
if errorlevel 1 goto invalid
goto run

:invalid
echo Please enter a number such as 20 or 35.50.
pause
goto menu

:run
cls
echo Checking the sample Terraform plan with a $%budget% monthly limit...
echo The first run may take longer while Azure prices are fetched.
echo.
call "%~dp0costguard.cmd" --plan "%~dp0test-plans\plan-a-small-add.json" --max-increase %budget% --strict
set "result=%errorlevel%"
echo.
if "%result%"=="0" echo RESULT: PASSED - The increase is within your limit.
if "%result%"=="1" echo RESULT: FAILED - The increase exceeds your limit.
if "%result%"=="2" echo RESULT: Could not complete the check. Read the error above and try again.
echo.
pause
goto menu

:done
popd
endlocal
exit /b 0

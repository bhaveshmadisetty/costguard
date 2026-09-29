@echo off
if not exist "%~dp0costguard.exe" goto python
"%~dp0costguard.exe" %*
exit /b %errorlevel%
:python
py "%~dp0costguard.py" %*
exit /b %errorlevel%

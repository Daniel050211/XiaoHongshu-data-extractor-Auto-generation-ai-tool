@echo off
cd /d "%~dp0"

if exist "%~dp0XHSWeeklyReport.exe" (
  start "" "%~dp0XHSWeeklyReport.exe"
  exit /b 0
)

set "PYW="

where pythonw >nul 2>nul
if %errorlevel%==0 set "PYW=pythonw"

if not defined PYW if exist "%LOCALAPPDATA%\Programs\Python\Python314\pythonw.exe" set "PYW=%LOCALAPPDATA%\Programs\Python\Python314\pythonw.exe"
if not defined PYW if exist "%LOCALAPPDATA%\Programs\Python\Python313\pythonw.exe" set "PYW=%LOCALAPPDATA%\Programs\Python\Python313\pythonw.exe"
if not defined PYW if exist "%LOCALAPPDATA%\Programs\Python\Python312\pythonw.exe" set "PYW=%LOCALAPPDATA%\Programs\Python\Python312\pythonw.exe"

if not defined PYW (
  echo Python not found. Please install Python 3.12-3.14 from https://www.python.org/downloads/
  echo Remember to tick "Add python.exe to PATH".
  pause
  exit /b 1
)

start "" "%PYW%" "xhs_app\app.py"
exit /b 0

@echo off
setlocal
title XAUUSD Trader - DEMO
cd /d "%~dp0\.."
set PYTHON_EXE=%CD%\.venv\Scripts\python.exe
if not exist "%PYTHON_EXE%" (
  set PYTHON_EXE=python
)

echo [INFO] Iniciando trader DEMO...
echo [INFO] Workspace: %CD%
echo [INFO] Python: %PYTHON_EXE%
echo.

"%PYTHON_EXE%" -m xau_trader.main --account demo --reset-state
set EXIT_CODE=%ERRORLEVEL%

echo.
if %EXIT_CODE% NEQ 0 (
  echo [ERROR] Trader encerrou com codigo %EXIT_CODE%.
) else (
  echo [INFO] Trader encerrou normalmente.
)
pause
exit /b %EXIT_CODE%

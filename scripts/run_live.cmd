@echo off
setlocal
title XAUUSD Trader - LIVE
cd /d "%~dp0\.."
set PYTHON_EXE=%LocalAppData%\Programs\Python\Python312\python.exe
if not exist "%PYTHON_EXE%" (
  echo [ERROR] Python nao encontrado em: %PYTHON_EXE%
  echo Ajuste o caminho no script ou instale Python 3.12.
  pause
  exit /b 1
)

echo [INFO] Iniciando trader LIVE...
echo [INFO] Workspace: %CD%
echo [INFO] Python: %PYTHON_EXE%
echo.

"%PYTHON_EXE%" -m xau_trader.main --account live --reset-state
set EXIT_CODE=%ERRORLEVEL%

echo.
if %EXIT_CODE% NEQ 0 (
  echo [ERROR] Trader encerrou com codigo %EXIT_CODE%.
) else (
  echo [INFO] Trader encerrou normalmente.
)
pause
exit /b %EXIT_CODE%

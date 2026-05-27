@echo off
setlocal
set PYTHON_EXE=%LocalAppData%\Programs\Python\Python312\python.exe
"%PYTHON_EXE%" -m xau_trader.main --account live


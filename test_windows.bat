@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" call run_windows.bat
call .venv\Scripts\activate.bat
python -m unittest discover -s tests -v
pause
endlocal

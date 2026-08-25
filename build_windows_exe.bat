@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" py -3 -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt pyinstaller
pyinstaller --noconfirm --clean monstrum_codex.spec
if errorlevel 1 exit /b 1
echo.
echo Build complete: dist\Monstrum Codex Infinite\Monstrum Codex Infinite.exe
pause
endlocal

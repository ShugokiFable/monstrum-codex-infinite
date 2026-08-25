@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo [Monstrum Codex] Preparing REAL-BROWSER official media cache and repair...
echo This uses a dedicated installed Edge, Chrome, Brave, or Opera browser window.
echo A visible browser window will open. Complete any Cloudflare check in that window.
echo.

if not exist ".venv\Scripts\python.exe" (
  py -3 -m venv .venv || goto :error
)

call ".venv\Scripts\activate.bat" || goto :error
python -m pip install --upgrade pip || goto :error
python -m pip install -r requirements.txt || goto :error
python -m tools.cache_official_images --transport browser %*
if errorlevel 1 goto :error

echo.
echo Official media caching and repair finished. Launch the app and press Ctrl+F5 once.
pause
exit /b 0

:error
echo.
echo The browser cache tool stopped with an error.
echo The solved browser session is kept in userdata\official-browser-profile-v2.
echo Copy the final error and userdata\official-image-cache-report.txt when reporting it.
pause
exit /b 1

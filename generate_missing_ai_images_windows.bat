@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo [Monstrum Codex] Generate missing AI and user portraits
echo This reads the image provider and keys/workflow saved in the app Settings.
echo Default limit is 10 images. Examples:
echo   generate_missing_ai_images_windows.bat --limit 25
echo   generate_missing_ai_images_windows.bat --provider comfyui --limit 0
echo   generate_missing_ai_images_windows.bat --provider openai --limit 10
echo.

if not exist ".venv\Scripts\python.exe" (
  py -3 -m venv .venv || goto :error
)
call ".venv\Scripts\activate.bat" || goto :error
python -m pip install -r requirements.txt || goto :error
python -m tools.generate_ai_images %*
if errorlevel 1 goto :error

echo.
echo Image generation finished. Reopen the app or press Ctrl+F5.
pause
exit /b 0

:error
echo.
echo The image generation tool stopped with an error.
echo See userdata\ai-image-generation-report.txt when available.
pause
exit /b 1

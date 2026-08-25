# Build on Windows with build_windows_exe.bat
from pathlib import Path
from PyInstaller.utils.hooks import collect_all

root = Path(SPECPATH)
webview_datas, webview_bins, webview_hidden = collect_all('webview')
uvicorn_datas, uvicorn_bins, uvicorn_hidden = collect_all('uvicorn')

a = Analysis(
    ['desktop.py'],
    pathex=[str(root)],
    binaries=webview_bins + uvicorn_bins,
    datas=[
        (str(root / 'web'), 'web'),
        (str(root / 'data'), 'data'),
        (str(root / 'workflows'), 'workflows'),
    ] + webview_datas + uvicorn_datas,
    hiddenimports=['app.main', 'app.db', 'app.providers', 'app.exports', 'app.official_sources'] + webview_hidden + uvicorn_hidden,
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True,
    name='Monstrum Codex Infinite',
    debug=False, bootloader_ignore_signals=False, strip=False, upx=True,
    console=False, disable_windowed_traceback=False,
)
coll = COLLECT(
    exe, a.binaries, a.datas,
    strip=False, upx=True, upx_exclude=[],
    name='Monstrum Codex Infinite',
)

"""Probe one wiki page through the real-browser rig; show raw structure."""
import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app import db  # noqa: E402
from app.browser_official_cache import _navigate, close_real_browser, launch_real_browser  # noqa: E402


async def main() -> None:
    db.init_db()
    entries, _ = db.list_entries(catalog_kind="official", limit=5)
    url = entries[0]["source_url"]
    session = await launch_real_browser(progress=print)
    try:
        page = await _navigate(session, url, print, timeout=45_000)
        await page.wait_for_timeout(800)
        info = await page.evaluate(
            """() => ({
              title: document.title,
              bodyChars: (document.body.innerText || '').length,
              hasMwContent: !!document.querySelector('#mw-content-text'),
              pCount: document.querySelectorAll('#mw-content-text p').length,
              bodySample: (document.body.innerText || '').slice(0, 600),
            })"""
        )
        for key, value in info.items():
            print(key, "=>", value)
    finally:
        await close_real_browser(session)


asyncio.run(main())

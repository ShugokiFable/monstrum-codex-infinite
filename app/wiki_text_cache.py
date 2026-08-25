"""Harvest official wiki article TEXT through the same real-browser rig that
cached the 1098 official images (Cloudflare-passing persistent profile v2).
Fills `lore` for Official entries whose lore is still the empty stub."""
from __future__ import annotations

import asyncio
import re
import time
from typing import Any, Callable

from app import db
from app.browser_official_cache import (
    _navigate,
    close_real_browser,
    launch_real_browser,
)

Progress = Callable[[str], None]

EXTRACT_JS = """
() => {
  const root = document.querySelector('#mw-content-text') || document.querySelector('article') || document.body;
  const paras = [];
  for (const p of root.querySelectorAll('p')) {
    const style = getComputedStyle(p);
    if (style.display === 'none' || style.visibility === 'hidden') continue;
    const t = (p.innerText || '').replace(/\\[\\d+\\]/g, '');
    const clean = t.replace(/\\s+/g, ' ').trim();
    if (clean.length >= 80) paras.push(clean);
    if (paras.length >= 8) break;
  }
  return paras.join('\\n\\n');
}
"""

STALE_MARKERS = (
    "enable javascript", "just a moment", "checking your browser",
    "are you a human", "verify you are", "cloudflare",
    # MediaWiki empty-article placeholder must never ship as lore
    "there is currently no text in this page",
)


def _looks_blocked(text: str) -> bool:
    low = (text or "").lower()
    return len(low) < 200 and any(m in low for m in STALE_MARKERS)


async def _wait_clear(page: Any, timeout_s: float = 40) -> bool:
    """Poll until the Cloudflare interstitial clears (or content appears)."""
    deadline = asyncio.get_event_loop().time() + timeout_s
    while asyncio.get_event_loop().time() < deadline:
        state = await page.evaluate(
            "() => ({t: document.title || '', ok: !!document.querySelector('#mw-content-text, article')})"
        )
        if state.get("ok") or "just a moment" not in str(state.get("t", "")).lower():
            return bool(state.get("ok"))
        await page.wait_for_timeout(1000)
    return False


async def harvest(entries: list[dict[str, Any]], progress: Progress = print,
                  delay_s: float = 0.4, max_pages: int | None = None) -> dict[str, int]:
    stats = {"scraped": 0, "skipped": 0, "failed": 0}
    session = await launch_real_browser(progress)
    page = session.index_page
    try:
        for index, entry in enumerate(entries, 1):
            url = entry.get("source_url") or ""
            if not url:
                stats["skipped"] += 1
                continue
            try:
                text = ""
                for attempt in (1, 2):  # challenge may navigate mid-read; one retry covers it
                    await _navigate(session, url, progress, timeout=45_000)
                    if not await _wait_clear(page):
                        raise RuntimeError("Cloudflare challenge did not clear in 40s")
                    await page.wait_for_timeout(400)
                    try:
                        text = (await page.evaluate(EXTRACT_JS) or "").strip()[:4000]
                        break
                    except Exception as exc:
                        if attempt == 2 or "Execution context" not in str(exc):
                            raise
                        progress(f"{entry['name']}: context reset by navigation, retrying")
                if _looks_blocked(text):
                    raise RuntimeError(f"challenge/gate page detected ({len(text)} chars)")
                if len(text) < 150:
                    raise RuntimeError(f"too little text ({len(text)} chars)")
                db.update_entry_fields(entry["id"], lore=text)
                stats["scraped"] += 1
                progress(f"[{index}/{len(entries)}] {entry['name']}: {len(text)} chars")
            except Exception as exc:
                stats["failed"] += 1
                progress(f"[{index}/{len(entries)}] {entry['name']}: FAILED - {exc}")
            if max_pages is not None and index >= max_pages:
                break
            await asyncio.sleep(delay_s)
    finally:
        await close_real_browser(session)
    return stats


def pending_text_entries(limit: int | None = None) -> list[dict[str, Any]]:
    items, _total = db.list_entries(catalog_kind="official", limit=2000)
    pending = [e for e in items if not (e.get("lore") or "").strip() and (e.get("source_url") or "")]
    return pending[:limit] if limit else pending


def cli() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Cache official article text via real browser")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    db.init_db()
    todo = pending_text_entries(args.limit)
    print(f"Official entries needing text: {len(todo)}. A browser window will open; keep it open.")
    started = time.time()
    result = asyncio.run(harvest(todo, progress=print, max_pages=args.limit))
    print(f"Done in {time.time()-started:.0f}s -> scraped {result['scraped']}, "
          f"failed {result['failed']}, skipped {result['skipped']}")

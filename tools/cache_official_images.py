from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# Direct execution sets sys.path to tools/, not the project root.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app import db  # noqa: E402
from app.browser_official_cache import cache_entries_with_real_browser  # noqa: E402
from app.official_media import pending_media_entries  # noqa: E402
from app.official_sources import cache_official_image  # noqa: E402


async def run(refresh: bool = False, transport: str = "browser") -> int:
    db.init_db()
    entries, total = db.list_entries(catalog_kind="official", limit=2000)
    pending = pending_media_entries(entries, refresh)
    print(f"Official entries: {total}. Media bundles to index/repair: {len(pending)}.")

    if transport == "http":
        print("Legacy HTTP mode only repairs the primary mugshot and is expected to fail behind Cloudflare.")
        cached = 0
        failures: list[str] = []
        for index, entry in enumerate(pending, 1):
            try:
                result = await cache_official_image(entry)
                db.update_entry_fields(entry["id"], **result)
                cached += 1
                print(f"[{index}/{len(pending)}] mugshot cached: {entry['name']}")
            except Exception as exc:
                message = f"{entry['name']}: {exc}"
                failures.append(message)
                print(f"[{index}/{len(pending)}] unavailable: {message}")
        result = {
            "cached": cached,
            "downloaded_assets": cached,
            "failed": len(failures),
            "failures": failures,
            "total": total,
            "complete": 0,
            "mugshots": cached,
            "portraits": 0,
            "entry_images": 0,
            "assets": cached,
        }
    else:
        print("Using a Playwright-owned persistent Chromium browser window.")
        print("The cache indexes Mugshot Image plus Profile Image, then repairs missing cards through each canonical entry page and stores all matched media.")
        print("A visible Edge, Chrome, Brave, or Opera window will open. Complete any site check and keep that window open.")
        result = await cache_entries_with_real_browser(entries, refresh=refresh, progress=print)

    report_path = db.USERDATA / "official-image-cache-report.txt"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        "Monstrum Codex Infinite official media cache report\n"
        f"Transport: {transport}\n"
        f"Entries complete: {result.get('complete', 0)} / {total}\n"
        f"Assets downloaded this run: {result.get('downloaded_assets', result.get('cached', 0))}\n"
        f"Mugshots available: {result.get('mugshots', 0)}\n"
        f"Standalone portraits available: {result.get('portraits', 0)}\n"
        f"Entry pages available: {result.get('entry_images', 0)}\n"
        f"Total local official assets: {result.get('assets', 0)}\n"
        f"Failures: {result['failed']}\n\n"
        + ("\n".join(result["failures"]) if result["failures"] else "No failures."),
        encoding="utf-8",
    )
    print(
        "Finished. "
        f"Complete entries {result.get('complete', 0)}/{total}; "
        f"mugshots {result.get('mugshots', 0)}; portraits {result.get('portraits', 0)}; "
        f"entry pages {result.get('entry_images', 0)}; failures {result['failed']}."
    )
    print(f"Report: {report_path}")
    return 0 if result.get("complete", 0) == total or not pending else 2


def main() -> None:
    parser = argparse.ArgumentParser(description="Cache and repair all official media: mugshots, standalone portraits, and entry pages.")
    parser.add_argument("--refresh", action="store_true", help="Redownload official media that is already cached")
    parser.add_argument(
        "--transport",
        choices=("browser", "http"),
        default="browser",
        help="Use a real installed browser (default) or the legacy mugshot-only HTTP resolver",
    )
    args = parser.parse_args()
    raise SystemExit(asyncio.run(run(args.refresh, args.transport)))


if __name__ == "__main__":
    main()

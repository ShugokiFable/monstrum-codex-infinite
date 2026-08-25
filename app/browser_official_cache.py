from __future__ import annotations

import asyncio
import os
import re
import shutil
import time
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import unquote, urljoin, urlparse

from PIL import Image

from . import db
from .official_media import (
    MEDIA_SCHEMA_VERSION,
    asset_list,
    asset_path_exists,
    classify_profile_filename,
    official_media_manifest,
    pending_media_entries,
)
from .official_sources import official_browser_mugshot_candidates, official_filename_stems
from .providers import _save_image_bytes

MGE_ROOT = "https://mgewiki.moe"
CATEGORY_URLS = (
    # The mugshot category supplies the compact card image. The Profile Image category
    # mixes encyclopedia page scans (``eng1``, ``jp1``...) and standalone portraits
    # (``Name 0.jpg``, ``Name 1.jpg``...). Both are indexed and cached separately.
    ("mugshot", f"{MGE_ROOT}/index.php?title=Category%3AMugshot_Image"),
    ("profile", f"{MGE_ROOT}/index.php?title=Category%3AProfile_Image"),
)


@dataclass(slots=True)
class BrowserRecord:
    filename: str
    file_page: str
    preview_url: str
    category: str


@dataclass(slots=True)
class BrowserSession:
    context: Any
    index_page: Any
    download_page: Any
    executable: Path
    playwright: Any


Progress = Callable[[str], None]


def _ascii(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    return normalized.encode("ascii", "ignore").decode("ascii")


def _normal(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", _ascii(value).lower())


def _file_base(filename: str) -> str:
    stem = Path(filename).stem
    stem = re.sub(r"(?i)(?:[\s_-]*(?:mug(?:shot)?|eng(?:lish)?[1-9]?|jp[1-9]?|profile(?:image)?))$", "", stem)
    return _normal(stem)


def _entry_aliases(entry: dict[str, Any]) -> set[str]:
    title = str((entry.get("extra") or {}).get("official_page_title") or entry.get("name") or "").strip()
    raw = [title, str(entry.get("name") or "")]
    raw.extend(str(value) for value in (entry.get("aliases") or []) if value)
    raw.extend(part.strip() for part in re.split(r"[/|\\]", title) if part.strip())
    raw.extend(match.strip() for match in re.findall(r"\(([^)]+)\)", title) if match.strip())
    raw.append(re.sub(r"\s*\([^)]*\)\s*", "", title).strip())
    # Reuse the deterministic filename variants so punctuation, spaces, slashes,
    # and parenthesized subtype names resolve the same way as direct file redirects.
    raw.extend(official_filename_stems(entry))
    return {_normal(value) for value in raw if _normal(value)}


def browser_record_score(entry: dict[str, Any], record: BrowserRecord) -> int:
    """Score a source file as a portrait candidate.

    v1.1.0-v1.1.4 preferred ``eng1`` encyclopedia-page scans. Those are valid
    reference documents, but they are the wrong asset for a portrait card. Mugshots
    now outrank every profile sheet and exact normalized names are required whenever
    the source category exposes them.
    """
    aliases = _entry_aliases(entry)
    file_norm = _normal(record.filename)
    base = _file_base(record.filename)
    score = -10_000
    if base in aliases:
        score = 2_000
    elif any(file_norm == f"{alias}mug" for alias in aliases):
        score = 1_900
    elif any(file_norm.startswith(alias) for alias in aliases if len(alias) >= 5):
        score = 650
    elif any(alias in file_norm for alias in aliases if len(alias) >= 7):
        score = 420

    lower = record.filename.lower()
    if record.category == "mugshot":
        score += 900
    else:
        score -= 1_200
    if "mug" in lower:
        score += 260
    if re.search(r"(?i)eng(?:lish)?[1-9]", lower) or "profile" in lower:
        score -= 700
    if "jp" in lower:
        score -= 120
    return score


def match_browser_record(entry: dict[str, Any], records: list[BrowserRecord]) -> BrowserRecord | None:
    mugshots = [record for record in records if record.category == "mugshot" or "mug" in record.filename.lower()]
    ranked = sorted(((browser_record_score(entry, record), record) for record in mugshots), key=lambda item: item[0], reverse=True)
    if not ranked or ranked[0][0] < 2_500:
        return None
    # Reject an ambiguous fuzzy match instead of assigning one portrait to two species.
    if len(ranked) > 1 and ranked[0][0] == ranked[1][0] and _file_base(ranked[0][1].filename) != _file_base(ranked[1][1].filename):
        return None
    return ranked[0][1]


def _local_media_exists(entry: dict[str, Any]) -> bool:
    local = str(entry.get("image_path") or "")
    return local.startswith("/media/") and (db.MEDIA_DIR / Path(local).name).exists()


def _cached_asset_is_portrait(entry: dict[str, Any]) -> bool:
    manifest = official_media_manifest(entry)
    return asset_path_exists(manifest.get("mugshot"))


def pending_portrait_entries(entries: list[dict[str, Any]], refresh: bool) -> list[dict[str, Any]]:
    """Backward-compatible alias for the v1.1.5 test/API name.

    v1.1.7 considers the whole official media bundle: mugshot, standalone
    portraits, and encyclopedia entry pages.
    """
    return pending_media_entries(entries, refresh)


def match_profile_records(entry: dict[str, Any], records: list[BrowserRecord]) -> dict[str, list[BrowserRecord]]:
    portraits: list[tuple[int, BrowserRecord]] = []
    entry_images: list[tuple[tuple[int, int], BrowserRecord]] = []
    for record in records:
        if record.category != "profile":
            continue
        classified = classify_profile_filename(entry, record.filename)
        if not classified:
            continue
        if classified["kind"] == "portrait":
            portraits.append((int(classified["index"]), record))
        else:
            # English pages first, then Japanese, each in numeric page order.
            language_rank = 0 if classified.get("language") == "en" else 1
            entry_images.append(((language_rank, int(classified["index"])), record))
    portraits.sort(key=lambda item: (item[0], item[1].filename.lower()))
    entry_images.sort(key=lambda item: (item[0], item[1].filename.lower()))
    return {
        "portraits": [record for _, record in portraits],
        "entry_images": [record for _, record in entry_images],
    }


def _candidate_browser_paths() -> list[Path]:
    values: list[str] = []
    override = os.environ.get("MONSTRUM_BROWSER", "").strip().strip('"')
    if override:
        values.append(override)

    local = os.environ.get("LOCALAPPDATA", "")
    pf = os.environ.get("PROGRAMFILES", "")
    pfx86 = os.environ.get("PROGRAMFILES(X86)", "")

    # Edge/Chrome are intentionally preferred over Opera for the cache worker.
    # Opera GX may replace or close its startup page while Playwright is attaching,
    # which caused the about:blank/TargetClosedError loop in v1.1.3.
    values.extend(
        [
            str(Path(pfx86) / "Microsoft" / "Edge" / "Application" / "msedge.exe") if pfx86 else "",
            str(Path(pf) / "Microsoft" / "Edge" / "Application" / "msedge.exe") if pf else "",
            str(Path(local) / "Microsoft" / "Edge" / "Application" / "msedge.exe") if local else "",
            str(Path(pf) / "Google" / "Chrome" / "Application" / "chrome.exe") if pf else "",
            str(Path(pfx86) / "Google" / "Chrome" / "Application" / "chrome.exe") if pfx86 else "",
            str(Path(local) / "Google" / "Chrome" / "Application" / "chrome.exe") if local else "",
            str(Path(pf) / "BraveSoftware" / "Brave-Browser" / "Application" / "brave.exe") if pf else "",
            str(Path(local) / "BraveSoftware" / "Brave-Browser" / "Application" / "brave.exe") if local else "",
            str(Path(local) / "Programs" / "Opera GX" / "opera.exe") if local else "",
            str(Path(local) / "Programs" / "Opera" / "opera.exe") if local else "",
        ]
    )
    for command in ("msedge", "msedge.exe", "chrome", "chrome.exe", "brave", "brave.exe", "opera", "opera.exe", "chromium", "chromium-browser"):
        found = shutil.which(command)
        if found:
            values.append(found)

    out: list[Path] = []
    for value in values:
        if not value:
            continue
        path = Path(value).expanduser()
        if path.exists() and path not in out:
            out.append(path)
    return out


def find_installed_browser() -> Path:
    paths = _candidate_browser_paths()
    if not paths:
        raise RuntimeError(
            "No Chromium browser was found. Install Microsoft Edge, Google Chrome, Brave, or Opera GX, "
            "or set MONSTRUM_BROWSER to the browser executable path."
        )
    return paths[0]


def _clear_restored_tabs(profile: Path) -> None:
    """Remove only Chromium session-restore files while preserving cookies/site data."""
    roots = (profile, profile / "Default")
    for root in roots:
        for name in ("Current Session", "Current Tabs", "Last Session", "Last Tabs"):
            try:
                (root / name).unlink(missing_ok=True)
            except OSError:
                pass
        sessions = root / "Sessions"
        if sessions.exists():
            try:
                shutil.rmtree(sessions)
            except OSError:
                pass


def _normalized_wiki_target(url: str) -> tuple[str, str]:
    parsed = urlparse(url)
    host = parsed.netloc.lower().removeprefix("www.")
    path = unquote(parsed.path or "/").rstrip("/") or "/"
    query = unquote(parsed.query).replace("+", " ").lower()
    if path.lower().startswith("/index.php/category:"):
        title = path.split("/", 2)[-1]
    else:
        match = re.search(r"(?:^|&)title=([^&]+)", query, re.I)
        title = match.group(1) if match else ""
    return host, _normal(title)


def _same_wiki_target(current: str, target: str) -> bool:
    current_host, current_title = _normalized_wiki_target(current)
    target_host, target_title = _normalized_wiki_target(target)
    if current_host != target_host:
        return False
    if target_title:
        return current_title == target_title
    return unquote(urlparse(current).path).rstrip("/") == unquote(urlparse(target).path).rstrip("/")


async def _collapse_to_single_page(context: Any, progress: Progress = print, controlled: Any | None = None) -> Any:
    """Keep one known-live page and close only confirmed extras."""
    await asyncio.sleep(0.25)
    pages = [page for page in context.pages if not page.is_closed()]
    if controlled is None or controlled.is_closed() or controlled not in pages:
        controlled = pages[0] if pages else await context.new_page()
    extras = [page for page in pages if page is not controlled]
    if extras:
        progress(f"Closing {len(extras)} extra browser tab(s); the cache uses one controlled tab only.")
    for page in extras:
        try:
            await page.close()
        except Exception:
            pass
    return controlled


async def _acquire_live_page(session: BrowserSession, progress: Progress = print) -> Any:
    """Return a live page, replacing a transient/closed startup page when needed."""
    preferred = session.index_page
    try:
        if preferred is not None and not preferred.is_closed():
            return preferred
    except Exception:
        pass

    try:
        pages = [page for page in session.context.pages if not page.is_closed()]
    except Exception as exc:
        raise RuntimeError(
            "The cache browser window was closed. Leave the dedicated browser window open until caching finishes."
        ) from exc

    page = pages[0] if pages else await session.context.new_page()
    session.index_page = page
    session.download_page = page
    progress("Recovered a live browser tab after Chromium replaced its startup page.")
    return page


async def _goto_with_response(
    session: BrowserSession,
    target: str,
    progress: Progress = print,
    timeout: int = 60_000,
    wait_until: str = "domcontentloaded",
) -> tuple[Any, Any]:
    """Navigate with one automatic page reacquisition retry."""
    last_error: Exception | None = None
    for attempt in range(2):
        page = await _acquire_live_page(session, progress)
        try:
            await page.bring_to_front()
            response = await page.goto(target, wait_until=wait_until, timeout=timeout)
            session.index_page = page
            session.download_page = page
            return page, response
        except Exception as exc:
            last_error = exc
            message = str(exc).lower()
            closed = "closed" in message or "target" in message
            try:
                closed = closed or page.is_closed()
            except Exception:
                closed = True
            if attempt == 0 and closed:
                try:
                    if not page.is_closed():
                        await page.close()
                except Exception:
                    pass
                session.index_page = None
                session.download_page = None
                await asyncio.sleep(0.6)
                continue
            raise
    raise RuntimeError(f"Browser navigation failed: {last_error}")


async def _navigate(session: BrowserSession, target: str, progress: Progress = print, timeout: int = 60_000) -> Any:
    page, _ = await _goto_with_response(session, target, progress, timeout, "domcontentloaded")
    return page


async def launch_real_browser(progress: Progress = print) -> BrowserSession:
    try:
        from playwright.async_api import async_playwright
    except Exception as exc:  # pragma: no cover - surfaced by Windows launcher.
        raise RuntimeError("Playwright is not installed. Re-run the BAT so requirements.txt is installed.") from exc

    executable = find_installed_browser()
    # v2 is deliberate: it avoids stale Opera/CDP lock files from v1.1.2-v1.1.3.
    profile = db.USERDATA / "official-browser-profile-v2"
    profile.mkdir(parents=True, exist_ok=True)
    _clear_restored_tabs(profile)
    progress(f"Opening dedicated cache browser: {executable.name}")

    browser_args = [
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-session-crashed-bubble",
        "--disable-features=InfiniteSessionRestore",
        "--disable-blink-features=AutomationControlled",
    ]
    if os.name != "nt":
        browser_args.append("--no-sandbox")

    playwright = await async_playwright().start()
    context = None
    try:
        context = await playwright.chromium.launch_persistent_context(
            user_data_dir=str(profile),
            executable_path=str(executable),
            headless=False,
            no_viewport=True,
            accept_downloads=True,
            ignore_default_args=["--enable-automation"],
            args=browser_args,
        )
        pages = [page for page in context.pages if not page.is_closed()]
        page = pages[0] if pages else await context.new_page()
        session = BrowserSession(context, page, page, executable, playwright)
        try:
            page = await _navigate(session, CATEGORY_URLS[0][1], progress)
        except Exception as exc:
            progress(f"Initial category navigation warning: {exc}")
            page = await _acquire_live_page(session, progress)
        page = await _collapse_to_single_page(context, progress, controlled=page)
        session.index_page = page
        session.download_page = page
        return session
    except Exception as exc:
        if context is not None:
            try:
                await context.close()
            except Exception:
                pass
        await playwright.stop()
        message = str(exc)
        if "user data directory is already in use" in message.lower() or "processsingleton" in message.lower():
            raise RuntimeError(
                "The dedicated cache browser profile is already open. Close the cache browser window and run the BAT again."
            ) from exc
        raise


async def close_real_browser(session: BrowserSession) -> None:
    try:
        await session.context.close()
    except Exception:
        pass
    try:
        await session.playwright.stop()
    except Exception:
        pass


async def _page_ready(page: Any, target_url: str | None = None) -> bool:
    try:
        title = (await page.title()).lower()
        body = (await page.locator("body").inner_text(timeout=1500)).lower()
        url = page.url.lower()
    except Exception:
        return False
    blocked = any(token in title or token in body for token in ("403 forbidden", "forbidden", "access denied", "just a moment", "checking your browser", "verify you are human"))
    target_ok = not target_url or _same_wiki_target(str(page.url), target_url)
    expected = target_ok and "mgewiki.moe" in url and (
        "media in category" in body or "monster girl encyclopedia" in body or "category:" in title
    )
    return expected and not blocked


async def _page_is_verification(page: Any) -> bool:
    try:
        title = (await page.title()).lower()
        body = (await page.locator("body").inner_text(timeout=1500)).lower()
    except Exception:
        return False
    return any(
        token in title or token in body
        for token in ("just a moment", "checking your browser", "verify you are human", "security verification", "challenge-platform")
    )


async def ensure_wiki_access(
    session: BrowserSession,
    progress: Progress = print,
    timeout: float = 600.0,
    target_url: str | None = None,
) -> Any:
    target = target_url or CATEGORY_URLS[0][1]
    page = await _acquire_live_page(session, progress)
    if not _same_wiki_target(str(page.url), target):
        try:
            page = await _navigate(session, target, progress)
        except Exception as exc:
            progress(f"Initial wiki navigation warning: {exc}")
            page = await _acquire_live_page(session, progress)
    if await _page_ready(page, target):
        return page

    progress("The wiki opened in a dedicated real browser. Complete any Cloudflare check there; the cache resumes automatically.")
    deadline = time.monotonic() + timeout
    last_navigation = time.monotonic()
    while time.monotonic() < deadline:
        page = await _acquire_live_page(session, progress)
        if await _page_ready(page, target):
            progress("Browser session accepted by the wiki.")
            return page
        # Do not reload an active human verification page. If verification has
        # completed but the site leaves us elsewhere, move back to the category.
        if (
            not _same_wiki_target(str(page.url), target)
            and time.monotonic() - last_navigation >= 4.0
            and not await _page_is_verification(page)
        ):
            try:
                page = await _navigate(session, target, progress)
            except Exception:
                pass
            last_navigation = time.monotonic()
        await asyncio.sleep(1.0)
    raise RuntimeError(
        "The dedicated browser session never gained access to mgewiki.moe. Complete the visible verification and keep "
        "that browser window open. The session is preserved in userdata\\official-browser-profile-v2."
    )


def _filename_from_file_url(url: str, title: str = "") -> str:
    value = title.removeprefix("File:").strip()
    if value:
        return value
    decoded = unquote(url)
    match = re.search(r"(?:File:|File%3A)([^?#]+)", decoded, re.I)
    return (match.group(1).replace("_", " ") if match else Path(urlparse(decoded).path).name).strip()


async def _extract_category_page(page: Any, category: str) -> tuple[list[BrowserRecord], str]:
    payload = await page.evaluate(
        r"""
        () => {
          const fileAnchors = [...document.querySelectorAll('a')].filter(a => {
            const href = a.href || '';
            return /(?:\/|=)File(?::|%3A)/i.test(href) || /\/File:/i.test(href);
          });
          const records = fileAnchors.map(a => {
            const box = a.closest('.gallerybox, .gallerytext, li, .mw-category-group, .mw-filepage-other-resolutions') || a.parentElement;
            const img = a.querySelector('img') || box?.querySelector('img') || null;
            return {
              href: a.href || '',
              title: a.getAttribute('title') || a.textContent || '',
              preview: img?.currentSrc || img?.src || ''
            };
          });
          const next = [...document.querySelectorAll('a')].find(a => {
            const text = (a.textContent || '').trim();
            return ((a.getAttribute('rel') || '').toLowerCase() === 'next' || /^next(?: page| \d+)?$/i.test(text)) && /Category/i.test(a.href || '');
          });
          return {records, next: next?.href || ''};
        }
        """
    )
    out: list[BrowserRecord] = []
    seen: set[str] = set()
    for item in payload.get("records", []):
        href = str(item.get("href") or "")
        if not href or href in seen:
            continue
        filename = _filename_from_file_url(href, str(item.get("title") or ""))
        if not re.search(r"\.(?:png|jpe?g|webp|gif)$", filename, re.I):
            continue
        seen.add(href)
        out.append(BrowserRecord(filename, href, str(item.get("preview") or ""), category))
    return out, str(payload.get("next") or "")



def _entry_source_urls(entry: dict[str, Any]) -> tuple[str, str]:
    source = str(entry.get("source_url") or "").strip()
    if not source:
        title = str((entry.get("extra") or {}).get("official_page_title") or entry.get("name") or "").strip()
        source = f"{MGE_ROOT}/index.php/{title.replace(' ', '_')}"
    source = source.rstrip("/")
    return source, f"{source}/Extra"


async def _extract_primary_entry_record(page: Any) -> BrowserRecord | None:
    """Resolve the entry page's own lead/infobox image.

    Some Mugshot Image filenames do not normalize back to the catalog title. The
    canonical species page already associates the correct lead image with the entry,
    so this is safer than progressively looser cross-species fuzzy matching.
    """
    item = await page.evaluate(
        r"""
        () => {
          const anchors = [...document.querySelectorAll('a.image, a[href*="/File:"], a[href*="File%3A"], a[href*="title=File%3A"]')];
          const ranked = [];
          for (const a of anchors) {
            const img = a.querySelector('img') || null;
            if (!img) continue;
            const src = img.currentSrc || img.src || '';
            const href = a.href || '';
            const title = a.getAttribute('title') || a.textContent || '';
            const lower = `${href} ${title} ${src}`.toLowerCase();
            if (!href || !src || /(logo|favicon|banner|button|icon|flag)/.test(lower)) continue;
            let score = 0;
            if (a.closest('.infobox, .portable-infobox, table.infobox, .mw-parser-output > table')) score += 1000;
            if (a.classList.contains('image')) score += 180;
            if (/mug(?:shot)?/.test(lower)) score += 420;
            const width = img.naturalWidth || img.width || 0;
            const height = img.naturalHeight || img.height || 0;
            if (width && height) {
              const ratio = width / height;
              if (ratio >= .55 && ratio <= 1.45) score += 180;
              if (height >= 180) score += 40;
            }
            ranked.push({score, href, title, preview: src});
          }
          ranked.sort((a, b) => b.score - a.score);
          return ranked[0] || null;
        }
        """
    )
    if not item:
        return None
    href = str(item.get("href") or "")
    filename = _filename_from_file_url(href, str(item.get("title") or ""))
    if not filename:
        filename = unquote(Path(urlparse(str(item.get("preview") or "")).path).name)
    return BrowserRecord(filename or "entry-page-lead-image", href, str(item.get("preview") or ""), "mugshot-page")


async def resolve_entry_page_mugshot_record(
    session: BrowserSession,
    entry: dict[str, Any],
    progress: Progress = print,
) -> BrowserRecord:
    source_url, _ = _entry_source_urls(entry)
    page = await _navigate(session, source_url, progress)
    page = await ensure_wiki_access(session, progress, target_url=source_url)
    record = await _extract_primary_entry_record(page)
    if record is None:
        raise RuntimeError("Canonical entry page did not expose a lead image")
    return record


async def collect_entry_profile_fallback_records(
    session: BrowserSession,
    entry: dict[str, Any],
    progress: Progress = print,
) -> list[BrowserRecord]:
    """Collect files linked by one entry's Extra page when category matching misses.

    Association comes from the canonical entry page rather than a global fuzzy match.
    We still run the strict filename classifier before assigning files to a media role.
    """
    _, extra_url = _entry_source_urls(entry)
    try:
        page = await _navigate(session, extra_url, progress)
        page = await ensure_wiki_access(session, progress, target_url=extra_url)
    except Exception:
        return []
    payload = await page.evaluate(
        r"""
        () => [...document.querySelectorAll('a')].map(a => {
          const href = a.href || '';
          if (!/(?:\/|=)File(?::|%3A)/i.test(href) && !/\/File:/i.test(href)) return null;
          const box = a.closest('.gallerybox, .gallerytext, li, figure, .thumb') || a.parentElement;
          const img = a.querySelector('img') || box?.querySelector('img') || null;
          return {href, title: a.getAttribute('title') || a.textContent || '', preview: img?.currentSrc || img?.src || ''};
        }).filter(Boolean)
        """
    )
    out: list[BrowserRecord] = []
    seen: set[str] = set()
    for item in payload:
        href = str(item.get("href") or "")
        if not href or href.lower() in seen:
            continue
        filename = _filename_from_file_url(href, str(item.get("title") or ""))
        if not re.search(r"\.(?:png|jpe?g|webp|gif)$", filename, re.I):
            continue
        if classify_profile_filename(entry, filename) is None:
            continue
        seen.add(href.lower())
        out.append(BrowserRecord(filename, href, str(item.get("preview") or ""), "profile"))
    return out


async def collect_image_index(session: BrowserSession, progress: Progress = print) -> list[BrowserRecord]:
    all_records: list[BrowserRecord] = []
    seen_files: set[str] = set()
    for category, start_url in CATEGORY_URLS:
        url = start_url
        visited: set[str] = set()
        page_no = 0
        while url and url not in visited and page_no < 12:
            visited.add(url)
            page_no += 1
            try:
                page = await _navigate(session, url, progress)
            except Exception as exc:
                progress(f"Category page navigation warning: {exc}")
                page = await _acquire_live_page(session, progress)
            page = await ensure_wiki_access(session, progress, target_url=url)
            records, next_url = await _extract_category_page(page, category)
            added = 0
            for record in records:
                key = record.file_page.lower()
                if key in seen_files:
                    continue
                seen_files.add(key)
                all_records.append(record)
                added += 1
            progress(f"Indexed {category} category page {page_no}: {added} image files.")
            url = next_url
    progress(f"Browser image index contains {len(all_records)} unique files.")
    return all_records


async def _resolve_original_url(session: BrowserSession, record: BrowserRecord) -> str:
    try:
        page = await _navigate(session, record.file_page)
    except Exception:
        page = await _acquire_live_page(session)
    candidates = await page.evaluate(
        """
        () => {
          const selectors = [
            '#file a[href]', '.fullImageLink a[href]', 'a.internal[href]',
            'meta[property="og:image"]', 'meta[name="twitter:image"]'
          ];
          const out = [];
          for (const selector of selectors) {
            for (const node of document.querySelectorAll(selector)) {
              const value = node.href || node.content || '';
              if (value && !out.includes(value)) out.push(value);
            }
          }
          for (const img of document.images) {
            const value = img.currentSrc || img.src || '';
            if (value && !out.includes(value)) out.push(value);
          }
          return out;
        }
        """
    )
    candidates = [str(value) for value in candidates if str(value).startswith("https://")]
    target = _normal(Path(record.filename).stem)
    ranked: list[tuple[int, str]] = []
    for candidate in candidates:
        if not (re.search(r"\.(?:png|jpe?g|webp|gif)(?:[?#].*)?$", candidate, re.I) or "/images/" in candidate):
            continue
        lower = candidate.lower()
        score = 0
        if target and target in _normal(unquote(candidate)):
            score += 600
        if "/images/" in lower:
            score += 80
        if "/thumb/" in lower:
            score -= 120
        if any(word in lower for word in ("logo", "icon", "site", "favicon", "banner")):
            score -= 400
        ranked.append((score, candidate))
    if ranked:
        return max(ranked, key=lambda item: item[0])[1]
    if record.preview_url:
        return record.preview_url
    raise RuntimeError(f"File page did not expose image bytes for {record.filename}")


def _extension(content_type: str, url: str, raw: bytes) -> str:
    ctype = content_type.split(";", 1)[0].strip().lower()
    mapping = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "image/gif": "gif", "image/avif": "avif"}
    if ctype in mapping:
        return mapping[ctype]
    suffix = Path(urlparse(url).path).suffix.lower().lstrip(".")
    if suffix in {"jpg", "jpeg", "png", "webp", "gif", "avif"}:
        return "jpg" if suffix == "jpeg" else suffix
    try:
        from io import BytesIO
        with Image.open(BytesIO(raw)) as image:
            return (image.format or "png").lower().replace("jpeg", "jpg")
    except Exception:
        return "png"


def _validate_image(raw: bytes) -> None:
    if not raw or len(raw) > 45 * 1024 * 1024:
        raise RuntimeError("Downloaded image is empty or larger than 45 MB")
    from io import BytesIO
    try:
        with Image.open(BytesIO(raw)) as image:
            image.verify()
    except Exception as exc:
        raise RuntimeError("Browser response was not a valid image") from exc


async def download_record(session: BrowserSession, record: BrowserRecord) -> tuple[bytes, str, str]:
    original_url = await _resolve_original_url(session, record)
    _, response = await _goto_with_response(session, original_url, timeout=75_000, wait_until="commit")
    if response is None:
        raise RuntimeError("Browser returned no response for image URL")
    if response.status >= 400:
        raise RuntimeError(f"Browser image request returned HTTP {response.status}")
    raw = await response.body()
    _validate_image(raw)
    final_url = response.url
    return raw, _extension(response.headers.get("content-type", ""), final_url, raw), final_url




async def download_direct_candidates(session: BrowserSession, entry: dict[str, Any]) -> tuple[bytes, str, str, str]:
    errors: list[str] = []
    clean = {**entry, "image_url": ""}
    for candidate in official_browser_mugshot_candidates(clean):
        try:
            _, response = await _goto_with_response(session, candidate, timeout=55_000, wait_until="commit")
            if response is None or response.status >= 400:
                raise RuntimeError(f"HTTP {None if response is None else response.status}")
            raw = await response.body()
            _validate_image(raw)
            final_url = response.url
            filename = unquote(Path(urlparse(final_url).path).name) or unquote(candidate.rsplit("/", 1)[-1])
            return raw, _extension(response.headers.get("content-type", ""), final_url, raw), final_url, filename
        except Exception as exc:
            errors.append(f"{unquote(candidate.rsplit('/', 1)[-1])}: {exc}")
    raise RuntimeError("Real browser could not resolve deterministic image names. " + "; ".join(errors[-4:]))


def _asset_record(kind: str, record: BrowserRecord, path: str, url: str) -> dict[str, Any]:
    classified_index = None
    language = ""
    if kind in {"portrait", "entry"}:
        stem = Path(record.filename).stem
        if kind == "portrait":
            match = re.search(r"(?:[\s_-]+)(\d+)$", stem)
            classified_index = int(match.group(1)) if match else None
        else:
            match = re.search(r"(?:[\s_-]+)(eng(?:lish)?|jp)[\s_-]*(\d+)$", stem, re.I)
            if match:
                language = "en" if match.group(1).lower().startswith("eng") else "jp"
                classified_index = int(match.group(2))
    return {
        "kind": kind,
        "filename": record.filename,
        "file_page": record.file_page,
        "url": url,
        "path": path,
        "index": classified_index,
        "language": language,
    }


def _existing_asset_by_filename(items: list[dict[str, Any]], filename: str) -> dict[str, Any] | None:
    needle = filename.casefold()
    for item in items:
        if str(item.get("filename") or "").casefold() == needle and asset_path_exists(item):
            return item
    return None


async def _cache_record_asset(
    session: BrowserSession,
    entry: dict[str, Any],
    record: BrowserRecord,
    kind: str,
    existing: list[dict[str, Any]],
    refresh: bool,
) -> tuple[dict[str, Any], bool]:
    reusable = None if refresh else _existing_asset_by_filename(existing, record.filename)
    if reusable:
        return reusable, False
    raw, ext, final_url = await download_record(session, record)
    name = str(entry.get("name") or "entry")
    suffix = "entry" if kind == "entry" else kind
    path = _save_image_bytes(raw, ext, f"official-{db.slugify(name)}-{suffix}")
    return _asset_record(kind, record, path, final_url), True


async def cache_entries_with_real_browser(
    entries: list[dict[str, Any]],
    *,
    refresh: bool = False,
    progress: Progress = print,
) -> dict[str, Any]:
    pending = pending_media_entries(entries, refresh)
    if not pending:
        counts = {"mugshots": 0, "portraits": 0, "entry_images": 0, "assets": 0}
        for entry in entries:
            manifest = official_media_manifest(entry)
            counts["mugshots"] += 1 if asset_path_exists(manifest.get("mugshot")) else 0
            counts["portraits"] += sum(1 for item in asset_list(manifest.get("portraits")) if asset_path_exists(item))
            counts["entry_images"] += sum(1 for item in asset_list(manifest.get("entry_images")) if asset_path_exists(item))
        counts["assets"] = counts["mugshots"] + counts["portraits"] + counts["entry_images"]
        return {"cached": 0, "failed": 0, "failures": [], "total": len(entries), "complete": len(entries), **counts}

    progress(
        f"Official media sync: {len(pending)} entr{'y' if len(pending) == 1 else 'ies'} need indexing or repair. "
        "The cache stores a mugshot, every standalone numbered portrait, and every English/Japanese entry page found."
    )
    session = await launch_real_browser(progress)
    failures: list[str] = []
    cached_entries = 0
    downloaded_assets = 0
    used_mugshots: set[str] = set()
    try:
        await ensure_wiki_access(session, progress)
        records = await collect_image_index(session, progress)
        mugshots = [record for record in records if record.category == "mugshot" or "mug" in record.filename.lower()]
        profiles = [record for record in records if record.category == "profile"]
        progress(
            f"Media index ready: {len(mugshots)} mugshots and {len(profiles)} profile-category files "
            f"for {len(entries)} official entries."
        )

        for entry_index, entry in enumerate(pending, 1):
            name = str(entry.get("name") or f"entry-{entry.get('id')}")
            old_extra = entry.get("extra") if isinstance(entry.get("extra"), dict) else {}
            manifest = official_media_manifest(entry)
            entry_failures: list[str] = []
            try:
                # 1. Dedicated mugshot used by cards and compact lists.
                mugshot_asset = manifest.get("mugshot") if isinstance(manifest.get("mugshot"), dict) else None
                if refresh or not asset_path_exists(mugshot_asset):
                    available = [record for record in mugshots if record.file_page.lower() not in used_mugshots]
                    record = match_browser_record(entry, available)
                    try:
                        if record is None:
                            raise RuntimeError("No unique mugshot category match")
                        raw, ext, final_url = await download_record(session, record)
                        filename = record.filename
                        file_page = record.file_page
                        used_mugshots.add(record.file_page.lower())
                    except Exception as category_exc:
                        progress(f"[{entry_index}/{len(pending)}] mugshot category match missed for {name}: {category_exc}")
                        try:
                            raw, ext, final_url, filename = await download_direct_candidates(session, entry)
                            file_page = ""
                            record = BrowserRecord(filename, file_page, final_url, "mugshot")
                        except Exception as redirect_exc:
                            progress(f"[{entry_index}/{len(pending)}] deterministic mugshot names missed for {name}: {redirect_exc}")
                            # Final authoritative fallback: use the lead image directly
                            # associated with this species' canonical wiki page.
                            record = await resolve_entry_page_mugshot_record(session, entry, progress)
                            raw, ext, final_url = await download_record(session, record)
                            filename = record.filename
                            file_page = record.file_page
                    mugshot_path = _save_image_bytes(raw, ext, f"official-{db.slugify(name)}-mugshot")
                    mugshot_asset = _asset_record("mugshot", record, mugshot_path, final_url)
                    downloaded_assets += 1

                # 2. Full-size standalone portrait files and encyclopedia page scans.
                matched = match_profile_records(entry, profiles)
                if not matched["portraits"] or not matched["entry_images"]:
                    fallback_records = await collect_entry_profile_fallback_records(session, entry, progress)
                    if fallback_records:
                        merged_records = list(profiles)
                        known_pages = {record.file_page.casefold() for record in merged_records}
                        merged_records.extend(record for record in fallback_records if record.file_page.casefold() not in known_pages)
                        matched = match_profile_records(entry, merged_records)
                old_portraits = asset_list(manifest.get("portraits"))
                old_entry_images = asset_list(manifest.get("entry_images"))
                portrait_assets: list[dict[str, Any]] = []
                entry_assets: list[dict[str, Any]] = []

                for record in matched["portraits"]:
                    try:
                        asset, downloaded = await _cache_record_asset(session, entry, record, "portrait", old_portraits, refresh)
                        portrait_assets.append(asset)
                        downloaded_assets += int(downloaded)
                    except Exception as exc:
                        entry_failures.append(f"portrait {record.filename}: {exc}")

                for record in matched["entry_images"]:
                    try:
                        asset, downloaded = await _cache_record_asset(session, entry, record, "entry", old_entry_images, refresh)
                        entry_assets.append(asset)
                        downloaded_assets += int(downloaded)
                    except Exception as exc:
                        entry_failures.append(f"entry image {record.filename}: {exc}")

                # Do not throw away previously valid local media merely because one
                # category page was incomplete during this run.
                portrait_names = {str(asset.get("filename") or "").casefold() for asset in portrait_assets}
                for asset in old_portraits:
                    filename_key = str(asset.get("filename") or "").casefold()
                    if asset_path_exists(asset) and filename_key not in portrait_names:
                        portrait_assets.append(asset)
                        portrait_names.add(filename_key)
                entry_names = {str(asset.get("filename") or "").casefold() for asset in entry_assets}
                for asset in old_entry_images:
                    filename_key = str(asset.get("filename") or "").casefold()
                    if asset_path_exists(asset) and filename_key not in entry_names:
                        entry_assets.append(asset)
                        entry_names.add(filename_key)

                # Category indexing is authoritative. Zero portraits is valid for a species,
                # while any actual download failure keeps the entry pending for the next run.
                complete = bool(mugshot_asset and asset_path_exists(mugshot_asset)) and not entry_failures
                updated_manifest = {
                    "schema": MEDIA_SCHEMA_VERSION,
                    "complete": complete,
                    "indexed_at": datetime.now(timezone.utc).isoformat(),
                    "mugshot": mugshot_asset,
                    "portraits": portrait_assets,
                    "entry_images": entry_assets,
                    "failures": entry_failures,
                }
                extra = {**old_extra, "official_media": updated_manifest}
                extra.update(
                    {
                        "official_image_filename": str((mugshot_asset or {}).get("filename") or ""),
                        "official_image_file_page": str((mugshot_asset or {}).get("file_page") or ""),
                        "official_image_category": "mugshot",
                        "official_mugshot_path": str((mugshot_asset or {}).get("path") or ""),
                        "official_portraits": portrait_assets,
                        "official_entry_images": entry_assets,
                        "official_image_cached_by": "playwright-multi-asset-v1.2.0",
                    }
                )
                db.update_entry_fields(
                    int(entry["id"]),
                    image_path=str((mugshot_asset or {}).get("path") or entry.get("image_path") or ""),
                    image_url=str((mugshot_asset or {}).get("url") or entry.get("image_url") or ""),
                    extra=extra,
                )
                if complete:
                    cached_entries += 1
                else:
                    failures.extend(f"{name}: {message}" for message in entry_failures)
                progress(
                    f"[{entry_index}/{len(pending)}] {name}: mugshot {'yes' if mugshot_asset else 'no'}, "
                    f"{len(portrait_assets)} portrait(s), {len(entry_assets)} entry page(s)"
                    + (f"; {len(entry_failures)} failed asset(s)" if entry_failures else "")
                )
            except Exception as exc:
                message = f"{name}: {exc}"
                failures.append(message)
                progress(f"[{entry_index}/{len(pending)}] unavailable: {message}")
    finally:
        await close_real_browser(session)

    # Re-read the database so counts include reused assets and successful partial updates.
    refreshed, _ = db.list_entries(catalog_kind="official", limit=2000)
    mugshot_count = portrait_count = entry_image_count = complete_count = 0
    for entry in refreshed:
        manifest = official_media_manifest(entry)
        mugshot_count += 1 if asset_path_exists(manifest.get("mugshot")) else 0
        portrait_count += sum(1 for item in asset_list(manifest.get("portraits")) if asset_path_exists(item))
        entry_image_count += sum(1 for item in asset_list(manifest.get("entry_images")) if asset_path_exists(item))
        complete_count += int(bool(manifest.get("complete")) and not manifest.get("failures") and asset_path_exists(manifest.get("mugshot")))

    return {
        "cached": cached_entries,
        "downloaded_assets": downloaded_assets,
        "failed": len(failures),
        "failures": failures,
        "total": len(entries),
        "complete": complete_count,
        "mugshots": mugshot_count,
        "portraits": portrait_count,
        "entry_images": entry_image_count,
        "assets": mugshot_count + portrait_count + entry_image_count,
    }


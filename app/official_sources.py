from __future__ import annotations

import asyncio
import html
import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, TypeVar
from urllib.parse import quote, urljoin, urlparse

import httpx

from . import db
from .providers import _save_image_bytes

try:  # curl-cffi ships a Chromium-like TLS/browser fingerprint for anti-bot fallbacks.
    from curl_cffi import requests as curl_requests
except Exception:  # pragma: no cover - the normal HTTP path remains available.
    curl_requests = None

MGE_ROOT = "https://mgewiki.moe"
MGE_API = f"{MGE_ROOT}/api.php"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36"
)
TRUSTED_IMAGE_HOST_SUFFIXES = (
    "mgewiki.moe",
    "miraheze.org",
    "wikimedia.org",
    "monstergirlsredux.moe",
    "sakura.ne.jp",
)
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif", "image/avif"}
T = TypeVar("T")


@dataclass(slots=True)
class _Payload:
    status_code: int
    url: str
    headers: dict[str, str]
    content: bytes

    @property
    def content_type(self) -> str:
        return self.headers.get("content-type", "").split(";", 1)[0].strip().lower()

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", errors="replace")


def _trusted_https_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    host = (parsed.hostname or "").lower()
    return parsed.scheme == "https" and any(host == suffix or host.endswith(f".{suffix}") for suffix in TRUSTED_IMAGE_HOST_SUFFIXES)


def _page_title(entry: dict[str, Any]) -> str:
    extra = entry.get("extra") if isinstance(entry.get("extra"), dict) else {}
    return str(extra.get("official_page_title") or entry.get("name") or "").strip()


def _ascii(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    return normalized.encode("ascii", "ignore").decode("ascii")


def _compact(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "", _ascii(value))


def official_filename_stems(entry: dict[str, Any]) -> list[str]:
    """Build the filename stems used by the wiki's profile and mugshot categories."""
    title = _page_title(entry)
    # The wiki normally removes spaces and punctuation from mugshot filenames.
    raw: list[str] = [_compact(title), title.replace(" ", ""), title]

    # Pages with slashes or parenthesized subtype names often use the subtype alone.
    parts = [part.strip() for part in re.split(r"[/|]", title) if part.strip()]
    parts.extend(match.strip() for match in re.findall(r"\(([^)]+)\)", title) if match.strip())
    parts.append(re.sub(r"\s*\([^)]*\)\s*", "", title).strip())
    for part in parts:
        raw.extend((_compact(part), part.replace(" ", ""), part))

    stems: list[str] = []
    for value in raw:
        if not value:
            continue
        for candidate in (value, value.replace(" ", ""), _compact(value)):
            candidate = candidate.strip()
            if candidate and candidate not in stems:
                stems.append(candidate)
    return stems


def official_browser_mugshot_candidates(entry: dict[str, Any]) -> list[str]:
    """Deterministic official portrait URLs, deliberately excluding profile-page scans."""
    results: list[str] = []
    existing = str(entry.get("image_url") or "").strip()
    extra = entry.get("extra") if isinstance(entry.get("extra"), dict) else {}
    existing_filename = str(extra.get("official_image_filename") or "").lower()
    existing_category = str(extra.get("official_image_category") or "").lower()
    if existing and _trusted_https_url(existing) and (existing_category == "mugshot" or "mug" in existing_filename):
        results.append(existing)

    for stem in official_filename_stems(entry)[:8]:
        for filename in (f"{stem}Mug.png", f"{stem}Mug.jpg", f"{stem}Mug.jpeg", f"{stem}Mug.webp"):
            url = f"{MGE_ROOT}/index.php/Special:Redirect/file/{quote(filename, safe='')}"
            if url not in results:
                results.append(url)
    return results


def official_browser_image_candidates(entry: dict[str, Any]) -> list[str]:
    """Browser candidates for legacy single-image resolution.

    Portrait consumers should call :func:`official_browser_mugshot_candidates` so a
    tall encyclopedia sheet can never masquerade as character art.
    """
    results = official_browser_mugshot_candidates(entry)
    stems = official_filename_stems(entry)
    for stem in stems[:2]:
        for filename in (f"{stem} eng1.png", f"{stem} eng1.jpg"):
            url = f"{MGE_ROOT}/index.php/Special:Redirect/file/{quote(filename, safe='')}"
            if url not in results:
                results.append(url)
    return results


async def _httpx_payload(url: str, *, params: dict[str, Any] | None, accept: str, timeout: float) -> _Payload:
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": accept,
        "Accept-Language": "en-CA,en;q=0.9",
        "Referer": f"{MGE_ROOT}/",
        "Cache-Control": "no-cache",
    }
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers=headers) as client:
        response = await client.get(url, params=params)
    return _Payload(response.status_code, str(response.url), {k.lower(): v for k, v in response.headers.items()}, response.content)


def _curl_payload_sync(url: str, *, params: dict[str, Any] | None, accept: str, timeout: float) -> _Payload:
    if curl_requests is None:
        raise RuntimeError("curl-cffi is unavailable")
    response = curl_requests.get(
        url,
        params=params,
        timeout=timeout,
        allow_redirects=True,
        impersonate="chrome",
        headers={
            "Accept": accept,
            "Accept-Language": "en-CA,en;q=0.9",
            "Referer": f"{MGE_ROOT}/",
            "Cache-Control": "no-cache",
        },
    )
    return _Payload(response.status_code, str(response.url), {k.lower(): v for k, v in response.headers.items()}, bytes(response.content))


async def _request_validated(
    url: str,
    *,
    params: dict[str, Any] | None,
    accept: str,
    timeout: float,
    validator: Callable[[_Payload], T],
) -> T:
    errors: list[str] = []
    transports = ["httpx"] + (["browser"] if curl_requests is not None else [])
    for transport in transports:
        try:
            payload = (
                await _httpx_payload(url, params=params, accept=accept, timeout=timeout)
                if transport == "httpx"
                else await asyncio.to_thread(_curl_payload_sync, url, params=params, accept=accept, timeout=timeout)
            )
            if payload.status_code >= 400:
                raise RuntimeError(f"HTTP {payload.status_code}")
            return validator(payload)
        except Exception as exc:
            errors.append(f"{transport}: {exc}")
    raise RuntimeError("; ".join(errors) or "request failed")


async def _get_json(url: str, params: dict[str, Any]) -> dict[str, Any]:
    def validate(payload: _Payload) -> dict[str, Any]:
        try:
            value = json.loads(payload.text)
        except Exception as exc:
            raise ValueError(f"expected JSON, received {payload.content_type or 'unknown content'}") from exc
        if not isinstance(value, dict):
            raise ValueError("JSON response was not an object")
        return value

    return await _request_validated(
        url,
        params=params,
        accept="application/json,text/plain;q=0.9,*/*;q=0.5",
        timeout=25,
        validator=validate,
    )


async def _get_html(url: str) -> tuple[str, str]:
    def validate(payload: _Payload) -> tuple[str, str]:
        text = payload.text
        if "<html" not in text.lower() and "<!doctype" not in text.lower():
            raise ValueError(f"expected HTML, received {payload.content_type or 'unknown content'}")
        if "cf-chl-" in text or "just a moment" in text.lower():
            raise ValueError("source returned a browser challenge")
        return text, payload.url

    return await _request_validated(
        url,
        params=None,
        accept="text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.7",
        timeout=30,
        validator=validate,
    )


async def _get_image(url: str, *, timeout: float = 65) -> tuple[bytes, str, str]:
    def validate(payload: _Payload) -> tuple[bytes, str, str]:
        if payload.content_type not in ALLOWED_IMAGE_TYPES:
            raise ValueError(f"expected an image, received {payload.content_type or 'unknown content'}")
        if not payload.content or len(payload.content) > 35 * 1024 * 1024:
            raise ValueError("image is empty or larger than 35 MB")
        return payload.content, payload.content_type, payload.url

    return await _request_validated(
        url,
        params=None,
        accept="image/avif,image/webp,image/png,image/jpeg,image/*;q=0.8,*/*;q=0.4",
        timeout=timeout,
        validator=validate,
    )


def _normal_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", _ascii(value).lower())


def _image_score(filename: str, title: str, width: int = 0, height: int = 0) -> int:
    file_norm = _normal_name(filename)
    title_norm = _normal_name(title)
    lower = filename.lower()
    score = 0
    if title_norm and title_norm in file_norm:
        score += 90
    if "mug" in lower:
        score += 220
    if "eng1" in lower:
        score += 150
    elif re.search(r"eng[23]", lower):
        score += 110
    if "profile" in lower:
        score += 70
    if any(word in lower for word in ("icon", "logo", "banner", "flag", "nav", "site")):
        score -= 250
    if "jp" in lower:
        score -= 20
    if width and height:
        if width >= 180 and height >= 180:
            score += 15
        ratio = width / max(height, 1)
        if 0.55 <= ratio <= 1.35:
            score += 15
    return score


def _best_api_image(payload: dict[str, Any], title: str) -> str:
    pages = payload.get("query", {}).get("pages", [])
    if isinstance(pages, dict):
        pages = list(pages.values())
    ranked: list[tuple[int, str]] = []
    for page in pages or []:
        info = (page.get("imageinfo") or [{}])[0]
        url = str(info.get("thumburl") or info.get("url") or "")
        if not _trusted_https_url(url):
            continue
        ranked.append(
            (
                _image_score(
                    str(page.get("title") or ""),
                    title,
                    int(info.get("thumbwidth") or info.get("width") or 0),
                    int(info.get("thumbheight") or info.get("height") or 0),
                ),
                url,
            )
        )
    return max(ranked, default=(-10_000, ""), key=lambda item: item[0])[1]


async def _resolve_via_api(title: str) -> str:
    # Query every file transcluded by the page, then prefer mugshots/profile images.
    generator_params = {
        "action": "query",
        "format": "json",
        "formatversion": "2",
        "redirects": "1",
        "titles": title,
        "generator": "images",
        "gimlimit": "max",
        "prop": "imageinfo",
        "iiprop": "url|mime|size",
        "iiurlwidth": "900",
    }
    try:
        url = _best_api_image(await _get_json(MGE_API, generator_params), title)
        if url:
            return url
    except Exception:
        pass

    pageimage_params = {
        "action": "query",
        "format": "json",
        "formatversion": "2",
        "redirects": "1",
        "prop": "pageimages|info",
        "piprop": "thumbnail|original",
        "pithumbsize": "1200",
        "titles": title,
    }
    payload = await _get_json(MGE_API, pageimage_params)
    pages = payload.get("query", {}).get("pages", [])
    if isinstance(pages, dict):
        pages = list(pages.values())
    if pages:
        page = pages[0]
        url = str((page.get("thumbnail") or {}).get("source") or (page.get("original") or {}).get("source") or "")
        if _trusted_https_url(url):
            return url
    raise ValueError("MediaWiki API did not expose a usable profile image")


async def _resolve_via_page(entry: dict[str, Any]) -> str:
    source_url = str(entry.get("source_url") or "").strip()
    if not source_url:
        raise ValueError("Official source URL is missing")
    text, final_url = await _get_html(source_url)
    candidates: list[tuple[int, str]] = []

    for pattern in (
        r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',
    ):
        match = re.search(pattern, text, re.I)
        if match:
            url = urljoin(final_url, html.unescape(match.group(1)))
            if _trusted_https_url(url):
                candidates.append((20, url))

    for tag in re.findall(r"<img\b[^>]*>", text, re.I):
        src_match = re.search(r"\bsrc=[\"']([^\"']+)", tag, re.I)
        if not src_match:
            continue
        url = urljoin(final_url, html.unescape(src_match.group(1)))
        if not _trusted_https_url(url):
            continue
        alt_match = re.search(r"\balt=[\"']([^\"']*)", tag, re.I)
        label = html.unescape(alt_match.group(1) if alt_match else "") + " " + url
        candidates.append((_image_score(label, _page_title(entry)), url))

    if not candidates:
        raise ValueError("Official page did not expose a usable preview image")
    return max(candidates, key=lambda item: item[0])[1]


async def resolve_official_image_url(entry: dict[str, Any], *, ignore_existing: bool = False) -> str:
    """Resolve official preview art with API, browser-fingerprint, filename, and HTML fallbacks."""
    existing = str(entry.get("image_url") or "").strip()
    if not ignore_existing and existing and _trusted_https_url(existing):
        return existing
    if entry.get("catalog_kind") != "official":
        raise ValueError("Only Official-library entries use the official image resolver")

    title = _page_title(entry)
    if not title:
        raise ValueError("Official page title is missing")

    errors: list[str] = []
    try:
        return await _resolve_via_api(title)
    except Exception as exc:
        errors.append(f"API: {exc}")

    # Deterministic Special:Redirect names work even when the API is challenged.
    for candidate in official_browser_image_candidates({**entry, "image_url": ""}):
        try:
            _, _, final_url = await _get_image(candidate, timeout=18)
            return final_url if _trusted_https_url(final_url) else candidate
        except Exception as exc:
            errors.append(f"file {candidate.rsplit('/', 1)[-1]}: {exc}")

    try:
        return await _resolve_via_page(entry)
    except Exception as exc:
        errors.append(f"page: {exc}")

    tail = "; ".join(errors[-4:])
    raise ValueError(f"No usable official preview was found. {tail}")


async def fetch_remote_image(url: str) -> tuple[bytes, str]:
    if not _trusted_https_url(url):
        raise ValueError("Image host is not in the official-source allowlist")
    raw, content_type, _ = await _get_image(url)
    ext = content_type.split("/", 1)[-1].replace("jpeg", "jpg")
    return raw, ext


async def cache_official_image(entry: dict[str, Any]) -> dict[str, str]:
    existing = str(entry.get("image_url") or "").strip()
    try:
        url = await resolve_official_image_url(entry)
        raw, ext = await fetch_remote_image(url)
    except Exception:
        # A stale URL from an earlier resolver should not permanently poison the entry.
        if not existing:
            raise
        url = await resolve_official_image_url(entry, ignore_existing=True)
        raw, ext = await fetch_remote_image(url)
    image_path = _save_image_bytes(raw, ext, f"official-{db.slugify(str(entry.get('name') or 'entry'))}")
    return {"image_url": url, "image_path": image_path}

from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Any, Iterable

from . import db

MEDIA_SCHEMA_VERSION = 3


def _ascii(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    return normalized.encode("ascii", "ignore").decode("ascii")


def normal_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", _ascii(value).lower())


def entry_media_aliases(entry: dict[str, Any]) -> set[str]:
    extra = entry.get("extra") if isinstance(entry.get("extra"), dict) else {}
    title = str(extra.get("official_page_title") or entry.get("name") or "").strip()
    values = [title, str(entry.get("name") or ""), str(entry.get("species") or "")]
    values.extend(str(value) for value in (entry.get("aliases") or []) if value)
    values.extend(part.strip() for part in re.split(r"[/|\\]", title) if part.strip())
    values.extend(match.strip() for match in re.findall(r"\(([^)]+)\)", title) if match.strip())
    values.append(re.sub(r"\s*\([^)]*\)\s*", "", title).strip())
    return {normal_name(value) for value in values if normal_name(value)}


def classify_profile_filename(entry: dict[str, Any], filename: str) -> dict[str, Any] | None:
    """Classify a Profile Image category filename for one official entry.

    The source category mixes full encyclopedia page scans and standalone character
    art. Examples include ``Apsara eng1.png`` and ``Apsara 0.jpg``. Exact normalized
    base-name matching prevents broad names from claiming a related species' files.
    """
    stem = Path(filename).stem.strip()
    aliases = entry_media_aliases(entry)

    # MediaWiki uploads are not fully consistent. Some use spaces/underscores,
    # while older files collapse the suffix directly into the species name.
    page_match = re.match(r"^(.*?)(?:[\s_-]+)?(eng(?:lish)?|jp)[\s_-]*(\d+)$", stem, re.I)
    if page_match:
        base, language, number = page_match.groups()
        if normal_name(base) not in aliases:
            return None
        lang = "en" if language.lower().startswith("eng") else "jp"
        return {"kind": "entry", "language": lang, "index": int(number), "filename": filename}

    portrait_match = re.match(r"^(.*?)(?:[\s_-]+)(\d+)$", stem, re.I)
    if not portrait_match:
        # Handles compact uploads such as ``AkaOni0.jpg`` without allowing a
        # broad prefix match to steal files from a related species.
        portrait_match = re.match(r"^(.*?)(\d+)$", stem, re.I)
    if portrait_match:
        base, number = portrait_match.groups()
        if normal_name(base) not in aliases:
            return None
        return {"kind": "portrait", "index": int(number), "filename": filename}

    # A few source portraits are uploaded as simply ``Name.jpg``. Exact alias
    # equality makes this safe while still excluding encyclopedia page scans.
    if normal_name(stem) in aliases:
        return {"kind": "portrait", "index": 0, "filename": filename}

    return None


def asset_path_exists(asset: dict[str, Any] | None) -> bool:
    if not isinstance(asset, dict):
        return False
    path = str(asset.get("path") or "")
    return path.startswith("/media/") and (db.MEDIA_DIR / Path(path).name).exists()


def asset_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def official_media_manifest(entry: dict[str, Any]) -> dict[str, Any]:
    extra = entry.get("extra") if isinstance(entry.get("extra"), dict) else {}
    raw = extra.get("official_media")
    manifest = dict(raw) if isinstance(raw, dict) else {}

    # Migrate v1.1.5's single mugshot fields into the multi-asset manifest without
    # discarding user-generated or attached replacement art.
    mugshot = manifest.get("mugshot") if isinstance(manifest.get("mugshot"), dict) else None
    category = str(extra.get("official_image_category") or "").lower()
    filename = str(extra.get("official_image_filename") or "")
    legacy_path = str(extra.get("official_mugshot_path") or extra.get("official_portrait_path") or entry.get("image_path") or "")
    if not mugshot and legacy_path and (category == "mugshot" or "mug" in filename.lower()):
        mugshot = {
            "kind": "mugshot",
            "filename": filename,
            "path": legacy_path,
            "url": str(entry.get("image_url") or ""),
            "file_page": str(extra.get("official_image_file_page") or ""),
        }

    portraits = asset_list(manifest.get("portraits") or extra.get("official_portraits"))
    entry_images = asset_list(manifest.get("entry_images") or extra.get("official_entry_images"))

    # v1.1.5 preserved the old profile-sheet path when it swapped the card image to
    # the mugshot. Reuse that file as an entry page instead of downloading it again.
    legacy_sheet_path = str(extra.get("official_profile_sheet_path") or "")
    legacy_sheet_filename = str(extra.get("official_profile_sheet_filename") or "")
    if legacy_sheet_path and legacy_sheet_filename and not any(str(item.get("filename") or "").casefold() == legacy_sheet_filename.casefold() for item in entry_images):
        classified = classify_profile_filename(entry, legacy_sheet_filename)
        if classified and classified.get("kind") == "entry":
            entry_images.append({
                "kind": "entry",
                "filename": legacy_sheet_filename,
                "path": legacy_sheet_path,
                "url": "",
                "file_page": "",
                "index": classified.get("index"),
                "language": classified.get("language", ""),
            })

    manifest["schema"] = int(manifest.get("schema") or 0)
    manifest["mugshot"] = mugshot
    manifest["portraits"] = portraits
    manifest["entry_images"] = entry_images
    manifest["complete"] = bool(manifest.get("complete"))
    manifest["failures"] = [str(value) for value in (manifest.get("failures") or []) if value]
    return manifest


def iter_manifest_assets(manifest: dict[str, Any]) -> Iterable[dict[str, Any]]:
    mugshot = manifest.get("mugshot")
    if isinstance(mugshot, dict):
        yield mugshot
    yield from asset_list(manifest.get("portraits"))
    yield from asset_list(manifest.get("entry_images"))


def manifest_local_counts(entry: dict[str, Any]) -> dict[str, int]:
    manifest = official_media_manifest(entry)
    mugshot = 1 if asset_path_exists(manifest.get("mugshot")) else 0
    portraits = sum(1 for item in asset_list(manifest.get("portraits")) if asset_path_exists(item))
    entry_images = sum(1 for item in asset_list(manifest.get("entry_images")) if asset_path_exists(item))
    return {
        "mugshots": mugshot,
        "portraits": portraits,
        "entry_images": entry_images,
        "assets": mugshot + portraits + entry_images,
    }


def manifest_is_complete(entry: dict[str, Any]) -> bool:
    manifest = official_media_manifest(entry)
    if int(manifest.get("schema") or 0) < MEDIA_SCHEMA_VERSION or not manifest.get("complete"):
        return False
    if manifest.get("failures"):
        return False
    if not asset_path_exists(manifest.get("mugshot")):
        return False
    return all(asset_path_exists(asset) for asset in iter_manifest_assets(manifest))


def pending_media_entries(entries: list[dict[str, Any]], refresh: bool = False) -> list[dict[str, Any]]:
    return [entry for entry in entries if refresh or not manifest_is_complete(entry)]

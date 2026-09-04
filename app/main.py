from __future__ import annotations

import base64
import csv
import io
import json
import mimetypes
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import db
from . import codex
from .exports import ccv3_png, charx_bytes, entry_to_ccv3, entry_to_lorebook
from .ai_media import local_image_exists, pending_generated_image_entries
from .official_media import manifest_is_complete, manifest_local_counts
from .official_sources import cache_official_image, fetch_remote_image, resolve_official_image_url
from .providers import (
    generate_comfy_image,
    generate_gemini_image,
    generate_lore,
    generate_openai_image,
    openrouter_models,
)

ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
WEB = ROOT / "web"

app = FastAPI(title="Monstrum Codex Infinite", version="1.6.1")


_BROWSER_CACHE_PROCESS: subprocess.Popen[Any] | None = None
_BROWSER_CACHE_LOG_HANDLE: Any = None
_AI_IMAGE_PROCESS: subprocess.Popen[Any] | None = None
_AI_IMAGE_LOG_HANDLE: Any = None

_AI_BATCH_MODULE = "tools.generate_ai_images"
_AI_BATCH_PROVIDERS = {
    "comfyui": "comfyui",
    "openai": "openai",
    "gemini": "gemini",
}
_AI_BATCH_KINDS = {
    "ai": "ai",
    "user": "user",
}
_AI_BATCH_KIND_JOIN = {
    ("ai",): "ai",
    ("user",): "user",
    ("ai", "user"): "ai,user",
    ("user", "ai"): "user,ai",
}


def _resolve_ai_batch_provider(requested: str) -> str:
    key = requested.strip().lower()
    if key == "default":
        settings = db.get_setting("ui", {}) or {}
        key = str(settings.get("defaultImageProvider") or "comfyui").strip().lower()
    try:
        return _AI_BATCH_PROVIDERS[key]
    except KeyError:
        raise HTTPException(
            400,
            "Batch generation supports ComfyUI, OpenAI API, or Gemini API. Manual subscription handoff is per-entry only.",
        ) from None


def _resolve_ai_batch_kinds(values: list[str]) -> tuple[str, ...]:
    resolved: list[str] = []
    seen: set[str] = set()
    for value in values:
        mapped = _AI_BATCH_KINDS.get(str(value).strip().lower())
        if mapped is None or mapped in seen:
            continue
        seen.add(mapped)
        resolved.append(mapped)
    if not resolved:
        return (_AI_BATCH_KINDS["ai"],)
    return tuple(resolved)


def _ai_batch_limit_arg(limit: int) -> str:
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 0 or limit > 2000:
        raise HTTPException(400, "Invalid batch limit")
    text = format(limit, "d")
    if re.fullmatch(r"[0-9]{1,4}", text) is None:
        raise HTTPException(400, "Invalid batch limit")
    return text


def _ai_batch_command(provider: str, kinds: tuple[str, ...], limit: int, refresh: bool) -> list[str]:
    try:
        provider_arg = _AI_BATCH_PROVIDERS[provider]
        kinds_arg = _AI_BATCH_KIND_JOIN[kinds]
    except KeyError:
        raise HTTPException(400, "Invalid batch generation arguments") from None
    command = [
        sys.executable,
        "-u",
        "-m",
        _AI_BATCH_MODULE,
        "--provider",
        provider_arg,
        "--kinds",
        kinds_arg,
        "--limit",
        _ai_batch_limit_arg(limit),
    ]
    if refresh:
        command.append("--refresh")
    if provider_arg in (_AI_BATCH_PROVIDERS["openai"], _AI_BATCH_PROVIDERS["gemini"]):
        command.append("--yes-hosted")
    return command


def _safe_media_path(filename: str) -> Path:
    if not isinstance(filename, str) or not filename or "\x00" in filename:
        raise HTTPException(400, "Invalid filename")
    if os.path.isabs(filename) or filename.startswith("/") or filename.startswith("\\"):
        raise HTTPException(400, "Invalid filename")
    if ".." in Path(filename).parts or ".." in filename.split("/") or ".." in filename.split("\\"):
        raise HTTPException(400, "Invalid filename")
    base_path = os.path.realpath(str(db.MEDIA_DIR))
    fullpath = os.path.normpath(os.path.join(base_path, filename))
    if not fullpath.startswith(base_path):
        raise HTTPException(400, "Invalid filename")
    real = os.path.realpath(fullpath)
    if os.path.commonpath([base_path, real]) != base_path:
        raise HTTPException(400, "Invalid filename")
    return Path(real)


def _official_cache_counts() -> dict[str, int]:
    items, total = db.list_entries(catalog_kind="official", limit=2000)
    counts = {
        "cached": 0,
        "complete": 0,
        "total": total,
        "mugshots": 0,
        "portraits": 0,
        "entry_images": 0,
        "assets": 0,
    }
    for item in items:
        local = manifest_local_counts(item)
        counts["mugshots"] += local["mugshots"]
        counts["portraits"] += local["portraits"]
        counts["entry_images"] += local["entry_images"]
        counts["assets"] += local["assets"]
        if manifest_is_complete(item):
            counts["complete"] += 1
    counts["cached"] = counts["complete"]
    return counts




def _ai_image_counts(kinds: tuple[str, ...] = ("ai",)) -> dict[str, int]:
    items = [item for item in db.all_entries() if item.get("catalog_kind") in set(kinds)]
    missing = pending_generated_image_entries(items, catalog_kinds=kinds, refresh=False)
    return {
        "total": len(items),
        "with_images": sum(1 for item in items if local_image_exists(item)),
        "missing": len(missing),
    }


def _ai_image_log_tail(lines: int = 10) -> list[str]:
    path = db.USERDATA / "ai-image-generation.log"
    if not path.exists():
        return []
    try:
        return path.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:]
    except Exception:
        return []

def _cache_log_tail(lines: int = 10) -> list[str]:
    path = db.USERDATA / "official-browser-cache.log"
    if not path.exists():
        return []
    try:
        return path.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:]
    except Exception:
        return []

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:17373", "http://localhost:17373"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup() -> None:
    db.init_db()


class EntryPayload(BaseModel):
    data: dict[str, Any]


class LorePayload(BaseModel):
    api_key: str = ""
    model: str
    concept: str
    world: str = ""
    tone: str = ""
    mature: bool = False
    temperature: float = Field(default=0.85, ge=0, le=2)


class ModelPayload(BaseModel):
    api_key: str = ""


class ImagePayload(BaseModel):
    provider: str
    api_key: str = ""
    model: str = ""
    prompt: str
    negative_prompt: str = ""
    size: str = "1024x1536"
    quality: str = "high"
    background: str = "opaque"
    aspect_ratio: str = "2:3"
    image_size: str = "2K"
    comfy_url: str = "http://127.0.0.1:8188"
    workflow: dict[str, Any] | None = None
    width: int = 832
    height: int = 1216
    seed: int = -1


class ImageBatchPayload(BaseModel):
    provider: str = "default"
    catalog_kinds: list[str] = Field(default_factory=lambda: ["ai"])
    limit: int = Field(default=10, ge=0, le=2000)
    refresh: bool = False
    confirm_hosted: bool = False


class SettingsPayload(BaseModel):
    settings: dict[str, Any]


class ImportPayload(BaseModel):
    entries: list[dict[str, Any]]
    mode: str = "merge"


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"ok": True, "version": app.version}


@app.get("/api/entries")
def entries(
    query: str = "",
    family: str = "",
    habitat: str = "",
    rarity: str = "",
    favorites: bool = False,
    catalog_kind: str = "",
    sort: str = "name",
    limit: int = 500,
    offset: int = 0,
) -> dict[str, Any]:
    items, total = db.list_entries(query, family, habitat, rarity, favorites, catalog_kind, sort, limit, offset)
    return {"items": items, "total": total, "facets": db.facets()}


@app.get("/api/entries/{entry_id}")
def entry(entry_id: int) -> dict[str, Any]:
    item = db.get_entry(entry_id)
    if not item:
        raise HTTPException(404, "Entry not found")
    item["codex_profile"] = codex.build(item)
    return item


@app.post("/api/entries")
def create_entry(payload: EntryPayload) -> dict[str, Any]:
    return db.create_entry(payload.data)


@app.put("/api/entries/{entry_id}")
def update_entry(entry_id: int, payload: EntryPayload) -> dict[str, Any]:
    item = db.update_entry(entry_id, payload.data)
    if not item:
        raise HTTPException(404, "Entry not found")
    return item


@app.delete("/api/entries/{entry_id}")
def delete_entry(entry_id: int) -> dict[str, Any]:
    if not db.delete_entry(entry_id):
        raise HTTPException(404, "Entry not found")
    return {"ok": True}


@app.post("/api/openrouter/models")
async def models(payload: ModelPayload) -> dict[str, Any]:
    try:
        return {"models": await openrouter_models(payload.api_key)}
    except Exception as exc:
        raise HTTPException(502, str(exc)) from exc


@app.post("/api/ai/lore")
async def ai_lore(payload: LorePayload) -> dict[str, Any]:
    try:
        return await generate_lore(**payload.model_dump())
    except Exception as exc:
        raise HTTPException(502, str(exc)) from exc


@app.post("/api/ai/image")
async def ai_image(payload: ImagePayload) -> dict[str, Any]:
    try:
        if payload.provider == "openai":
            return await generate_openai_image(
                api_key=payload.api_key,
                model=payload.model,
                prompt=payload.prompt,
                size=payload.size,
                quality=payload.quality,
                background=payload.background,
            )
        if payload.provider == "gemini":
            return await generate_gemini_image(
                api_key=payload.api_key,
                model=payload.model,
                prompt=payload.prompt,
                aspect_ratio=payload.aspect_ratio,
                image_size=payload.image_size,
            )
        if payload.provider == "comfyui":
            if not payload.workflow:
                raise ValueError("ComfyUI API workflow JSON is required")
            return await generate_comfy_image(
                base_url=payload.comfy_url,
                workflow=payload.workflow,
                prompt=payload.prompt,
                negative_prompt=payload.negative_prompt,
                width=payload.width,
                height=payload.height,
                seed=payload.seed,
            )
        raise ValueError(f"Unknown image provider: {payload.provider}")
    except Exception as exc:
        raise HTTPException(502, str(exc)) from exc


@app.post("/api/ai/image-batch-launch")
def launch_ai_image_batch(payload: ImageBatchPayload) -> dict[str, Any]:
    global _AI_IMAGE_PROCESS, _AI_IMAGE_LOG_HANDLE
    if getattr(sys, "frozen", False):
        raise HTTPException(501, "The source-package batch image helper is unavailable inside the compiled shell. Run generate_missing_ai_images_windows.bat beside the app.")
    provider = _resolve_ai_batch_provider(payload.provider)
    if provider in {_AI_BATCH_PROVIDERS["openai"], _AI_BATCH_PROVIDERS["gemini"]} and not payload.confirm_hosted:
        raise HTTPException(400, "Hosted API generation may be billable and requires confirmation")
    kinds = _resolve_ai_batch_kinds(payload.catalog_kinds)
    if _AI_IMAGE_PROCESS is not None and _AI_IMAGE_PROCESS.poll() is None:
        return {"started": False, "running": True, "provider": provider, "catalog_kinds": kinds, **_ai_image_counts(kinds)}

    log_path = db.USERDATA / "ai-image-generation.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        if _AI_IMAGE_LOG_HANDLE is not None:
            _AI_IMAGE_LOG_HANDLE.close()
    except Exception:
        pass
    _AI_IMAGE_LOG_HANDLE = log_path.open("w", encoding="utf-8")
    command = _ai_batch_command(provider, kinds, payload.limit, payload.refresh)
    flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) if os.name == "nt" else 0
    try:
        _AI_IMAGE_PROCESS = subprocess.Popen(
            command,
            cwd=str(db.APP_ROOT),
            stdout=_AI_IMAGE_LOG_HANDLE,
            stderr=subprocess.STDOUT,
            shell=False,
            creationflags=flags,
        )
    except Exception as exc:
        raise HTTPException(500, f"Could not start batch image generation: {exc}") from exc
    return {"started": True, "running": True, "provider": provider, "catalog_kinds": kinds, **_ai_image_counts(kinds), "log": str(log_path)}


@app.get("/api/ai/image-batch-status")
def ai_image_batch_status(catalog_kinds: str = "ai") -> dict[str, Any]:
    kinds = tuple(dict.fromkeys(kind for kind in (part.strip().lower() for part in catalog_kinds.split(",")) if kind in {"ai", "user"})) or ("ai",)
    running = _AI_IMAGE_PROCESS is not None and _AI_IMAGE_PROCESS.poll() is None
    exit_code = None if running or _AI_IMAGE_PROCESS is None else _AI_IMAGE_PROCESS.returncode
    return {
        "running": running,
        "exit_code": exit_code,
        "catalog_kinds": kinds,
        **_ai_image_counts(kinds),
        "log_tail": _ai_image_log_tail(),
    }


@app.post("/api/official/{entry_id}/resolve-image")
async def official_resolve_image(entry_id: int) -> dict[str, str]:
    item = db.get_entry(entry_id)
    if not item:
        raise HTTPException(404, "Entry not found")
    if item.get("catalog_kind") != "official":
        raise HTTPException(400, "Entry is not in the Official library")
    try:
        image_url = await resolve_official_image_url(item)
        saved = db.update_entry_fields(entry_id, image_url=image_url)
        return {"image_url": image_url, "image_path": str((saved or {}).get("image_path") or "")}
    except Exception as exc:
        raise HTTPException(502, str(exc)) from exc


@app.post("/api/official/{entry_id}/cache-image")
async def official_cache_image(entry_id: int) -> dict[str, str]:
    item = db.get_entry(entry_id)
    if not item:
        raise HTTPException(404, "Entry not found")
    if item.get("catalog_kind") != "official":
        raise HTTPException(400, "Entry is not in the Official library")
    try:
        result = await cache_official_image(item)
        db.update_entry_fields(entry_id, **result)
        return result
    except Exception as exc:
        raise HTTPException(502, str(exc)) from exc


@app.get("/api/official/{entry_id}/image")
async def official_image(entry_id: int) -> Response:
    item = db.get_entry(entry_id)
    if not item or item.get("catalog_kind") != "official":
        raise HTTPException(404, "Official entry not found")
    local = str(item.get("image_path") or "")
    if local.startswith("/media/"):
        path = db.MEDIA_DIR / Path(local).name
        if path.exists():
            return FileResponse(path)
    try:
        image_url = await resolve_official_image_url(item)
        if image_url != item.get("image_url"):
            db.update_entry_fields(entry_id, image_url=image_url)
        raw, ext = await fetch_remote_image(image_url)
        media_type = "image/jpeg" if ext in {"jpg", "jpeg"} else f"image/{ext}"
        return Response(raw, media_type=media_type, headers={"Cache-Control": "public, max-age=86400"})
    except Exception as exc:
        raise HTTPException(404, str(exc)) from exc


@app.post("/api/official/cache-browser-launch")
def launch_official_browser_cache() -> dict[str, Any]:
    global _BROWSER_CACHE_PROCESS, _BROWSER_CACHE_LOG_HANDLE
    if getattr(sys, "frozen", False):
        raise HTTPException(501, "The source-package browser cache helper is unavailable inside the compiled shell. Run cache_official_images_windows.bat beside the app.")
    if _BROWSER_CACHE_PROCESS is not None and _BROWSER_CACHE_PROCESS.poll() is None:
        counts = _official_cache_counts()
        return {"started": False, "running": True, **counts}

    log_path = db.USERDATA / "official-browser-cache.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        if _BROWSER_CACHE_LOG_HANDLE is not None:
            _BROWSER_CACHE_LOG_HANDLE.close()
    except Exception:
        pass
    _BROWSER_CACHE_LOG_HANDLE = log_path.open("w", encoding="utf-8")
    command = [sys.executable, "-u", "-m", "tools.cache_official_images", "--transport", "browser"]
    flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) if os.name == "nt" else 0
    try:
        _BROWSER_CACHE_PROCESS = subprocess.Popen(
            command,
            cwd=str(db.APP_ROOT),
            stdout=_BROWSER_CACHE_LOG_HANDLE,
            stderr=subprocess.STDOUT,
            creationflags=flags,
        )
    except Exception as exc:
        raise HTTPException(500, f"Could not start the real-browser cache helper: {exc}") from exc
    counts = _official_cache_counts()
    return {"started": True, "running": True, **counts, "log": str(log_path)}


@app.get("/api/official/cache-browser-status")
def official_browser_cache_status() -> dict[str, Any]:
    running = _BROWSER_CACHE_PROCESS is not None and _BROWSER_CACHE_PROCESS.poll() is None
    exit_code = None if running or _BROWSER_CACHE_PROCESS is None else _BROWSER_CACHE_PROCESS.returncode
    counts = _official_cache_counts()
    return {
        "running": running,
        "exit_code": exit_code,
        **counts,
        "remaining": max(counts["total"] - counts["complete"], 0),
        "log_tail": _cache_log_tail(),
    }


@app.get("/api/settings")
def get_settings() -> dict[str, Any]:
    return db.get_setting("ui", {})


@app.put("/api/settings")
def save_settings(payload: SettingsPayload) -> dict[str, Any]:
    # Keys are stored locally in userdata/codex.sqlite3. The UI labels this clearly.
    db.set_setting("ui", payload.settings)
    return {"ok": True}


@app.post("/api/import")
def import_json(payload: ImportPayload) -> dict[str, Any]:
    return db.import_entries(payload.entries, payload.mode)


@app.post("/api/import/file")
async def import_file(file: UploadFile = File(...), mode: str = Form("merge")) -> dict[str, Any]:
    raw = await file.read()
    name = (file.filename or "").lower()
    try:
        if name.endswith(".csv"):
            text = raw.decode("utf-8-sig")
            rows = list(csv.DictReader(io.StringIO(text)))
            entries = []
            for row in rows:
                cooked = dict(row)
                for field in ("abilities", "weaknesses", "aliases", "tags"):
                    if field in cooked:
                        cooked[field] = [x.strip() for x in str(cooked[field]).split("|") if x.strip()]
                entries.append(cooked)
        else:
            parsed = json.loads(raw.decode("utf-8"))
            entries = parsed.get("entries", parsed) if isinstance(parsed, dict) else parsed
        if not isinstance(entries, list):
            raise ValueError("Import file must contain a JSON list or an object with an entries list")
        return db.import_entries(entries, mode)
    except Exception as exc:
        raise HTTPException(400, f"Import failed: {exc}") from exc


@app.get("/api/export/codex.json")
def export_codex() -> Response:
    payload = {"format": "monstrum-codex-v1", "entries": db.all_entries()}
    data = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    return Response(data, media_type="application/json", headers={"Content-Disposition": 'attachment; filename="monstrum-codex-backup.json"'})


def _avatar_bytes(entry: dict[str, Any]) -> bytes | None:
    path = entry.get("image_path", "")
    if not path.startswith("/media/"):
        return None
    local = db.MEDIA_DIR / Path(path).name
    return local.read_bytes() if local.exists() else None


@app.get("/api/export/ccv3/{entry_id}.json")
def export_ccv3(entry_id: int) -> Response:
    item = db.get_entry(entry_id)
    if not item:
        raise HTTPException(404, "Entry not found")
    data = json.dumps(entry_to_ccv3(item), ensure_ascii=False, indent=2).encode("utf-8")
    filename = f"{item['slug']}-ccv3.json"
    return Response(data, media_type="application/json", headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@app.get("/api/export/ccv3/{entry_id}.png")
def export_ccv3_png(entry_id: int) -> Response:
    item = db.get_entry(entry_id)
    if not item:
        raise HTTPException(404, "Entry not found")
    data = ccv3_png(entry_to_ccv3(item), _avatar_bytes(item))
    return Response(data, media_type="image/png", headers={"Content-Disposition": f'attachment; filename="{item["slug"]}-ccv3.png"'})


@app.get("/api/export/ccv3/{entry_id}.charx")
def export_charx(entry_id: int) -> Response:
    item = db.get_entry(entry_id)
    if not item:
        raise HTTPException(404, "Entry not found")
    data = charx_bytes(entry_to_ccv3(item), _avatar_bytes(item))
    return Response(data, media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{item["slug"]}.charx"'})


@app.get("/api/export/lorebook/{entry_id}.json")
def export_lorebook(entry_id: int) -> Response:
    item = db.get_entry(entry_id)
    if not item:
        raise HTTPException(404, "Entry not found")
    data = json.dumps(entry_to_lorebook(item), ensure_ascii=False, indent=2).encode("utf-8")
    return Response(data, media_type="application/json", headers={"Content-Disposition": f'attachment; filename="{item["slug"]}-lorebook.json"'})


@app.post("/api/media")
async def upload_media(file: UploadFile = File(...)) -> dict[str, str]:
    raw = await file.read()
    if len(raw) > 30 * 1024 * 1024:
        raise HTTPException(413, "Image is larger than 30 MB")
    media_type = file.content_type or mimetypes.guess_type(file.filename or "")[0] or ""
    if not media_type.startswith("image/"):
        raise HTTPException(400, "Only image files are accepted")
    suffix = Path(file.filename or "image.png").suffix.lower() or ".png"
    safe = f"upload-{db.slugify(Path(file.filename or 'image').stem)}-{db.utc_now().replace(':','').replace('+','')}{suffix}"
    path = db.MEDIA_DIR / safe
    path.write_bytes(raw)
    return {"image_path": f"/media/{safe}"}


@app.get("/media/{filename}")
def media(filename: str) -> FileResponse:
    path = _safe_media_path(filename)
    if not path.is_file():
        raise HTTPException(404, "Media not found")
    return FileResponse(path)


app.mount("/assets", StaticFiles(directory=WEB / "assets"), name="assets")


@app.get("/{path:path}")
def spa(path: str) -> FileResponse:
    return FileResponse(WEB / "index.html")

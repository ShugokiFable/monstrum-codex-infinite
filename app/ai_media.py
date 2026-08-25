from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Awaitable, Callable, Iterable

from . import db
from .providers import generate_comfy_image, generate_gemini_image, generate_openai_image

Progress = Callable[[str], None]
SUPPORTED_BATCH_PROVIDERS = {"comfyui", "openai", "gemini"}
SUPPORTED_CATALOG_KINDS = {"ai", "user"}


def local_image_exists(entry: dict[str, Any]) -> bool:
    path = str(entry.get("image_path") or "")
    return path.startswith("/media/") and (db.MEDIA_DIR / Path(path).name).is_file()


def entry_needs_generated_image(entry: dict[str, Any], *, refresh: bool = False) -> bool:
    if str(entry.get("catalog_kind") or "") not in SUPPORTED_CATALOG_KINDS:
        return False
    return refresh or not local_image_exists(entry)


def pending_generated_image_entries(
    entries: Iterable[dict[str, Any]],
    *,
    catalog_kinds: Iterable[str] = ("ai",),
    refresh: bool = False,
) -> list[dict[str, Any]]:
    allowed = {str(kind).strip().lower() for kind in catalog_kinds if str(kind).strip().lower() in SUPPORTED_CATALOG_KINDS}
    if not allowed:
        allowed = {"ai"}
    return [entry for entry in entries if str(entry.get("catalog_kind") or "") in allowed and entry_needs_generated_image(entry, refresh=refresh)]


def build_entry_image_prompt(entry: dict[str, Any]) -> str:
    explicit = str(entry.get("image_prompt") or "").strip()
    if explicit:
        return explicit
    appearance = str(entry.get("appearance") or "").strip()
    habitat = str(entry.get("habitat") or "").strip()
    species = str(entry.get("species") or entry.get("name") or "monster woman").strip()
    return (
        f"Full-body fantasy field-guide portrait of {entry.get('name')}, an unambiguously adult {species}. "
        f"{appearance} Environment: {habitat or 'a species-appropriate habitat'}. "
        "Anatomically coherent fantasy hybrid design, clear face, complete silhouette, natural pose, "
        "detailed materials, cinematic atmospheric lighting, vertical 2:3 composition, no text, no watermark."
    ).strip()


def build_entry_negative_prompt(entry: dict[str, Any]) -> str:
    explicit = str(entry.get("negative_prompt") or "").strip()
    if explicit:
        return explicit
    return "minor, child, young-looking, low quality, malformed anatomy, extra limbs, duplicate body parts, text, watermark, logo"


def provider_requirements(settings: dict[str, Any], provider: str) -> tuple[bool, str]:
    provider = provider.strip().lower()
    if provider == "openai":
        return bool(str(settings.get("openaiKey") or "").strip()), "OpenAI API key"
    if provider == "gemini":
        return bool(str(settings.get("geminiKey") or "").strip()), "Google AI Studio API key"
    if provider == "comfyui":
        raw = str(settings.get("comfyWorkflow") or "").strip()
        if not raw:
            return False, "ComfyUI API workflow JSON"
        try:
            parsed = json.loads(raw)
        except Exception:
            return False, "valid ComfyUI API workflow JSON"
        return isinstance(parsed, dict) and bool(parsed), "ComfyUI API workflow JSON"
    return False, "supported image provider"


async def generate_entry_image(
    entry: dict[str, Any],
    *,
    settings: dict[str, Any],
    provider: str,
) -> dict[str, Any]:
    provider = provider.strip().lower()
    if provider not in SUPPORTED_BATCH_PROVIDERS:
        raise ValueError("Batch generation supports ComfyUI, OpenAI API, or Gemini API. Manual subscription handoff is per-entry only.")
    ready, requirement = provider_requirements(settings, provider)
    if not ready:
        raise ValueError(f"Missing {requirement} in Settings")

    prompt = build_entry_image_prompt(entry)
    negative = build_entry_negative_prompt(entry)
    if provider == "openai":
        result = await generate_openai_image(
            api_key=str(settings.get("openaiKey") or ""),
            model=str(settings.get("openaiModel") or "gpt-image-2"),
            prompt=prompt,
            size=str(settings.get("batchOpenAIImageSize") or "1024x1536"),
            quality=str(settings.get("batchOpenAIQuality") or "high"),
            background="opaque",
        )
    elif provider == "gemini":
        result = await generate_gemini_image(
            api_key=str(settings.get("geminiKey") or ""),
            model=str(settings.get("geminiModel") or "gemini-3.1-flash-image"),
            prompt=prompt,
            aspect_ratio=str(settings.get("batchGeminiAspect") or "2:3"),
            image_size=str(settings.get("batchGeminiSize") or "2K"),
        )
    else:
        workflow = json.loads(str(settings.get("comfyWorkflow") or "{}"))
        result = await generate_comfy_image(
            base_url=str(settings.get("comfyUrl") or "http://127.0.0.1:8188"),
            workflow=workflow,
            prompt=prompt,
            negative_prompt=negative,
            width=int(settings.get("batchWidth") or 832),
            height=int(settings.get("batchHeight") or 1216),
            seed=-1,
            timeout_seconds=int(settings.get("batchTimeoutSeconds") or 600),
        )

    extra = dict(entry.get("extra") or {})
    history = list(extra.get("image_generation_history") or [])
    history.append({
        "provider": result.get("provider") or provider,
        "model": result.get("model") or "",
        "image_path": result.get("image_path") or "",
        "created_at": db.utc_now(),
        "prompt": prompt,
    })
    extra["image_generation_history"] = history[-12:]
    extra["last_image_generation"] = history[-1]
    saved = db.update_entry_fields(int(entry["id"]), image_path=str(result["image_path"]), extra=extra)
    if not saved:
        raise RuntimeError(f"Entry disappeared while saving generated art: {entry.get('name')}")
    return saved


async def generate_missing_entry_images(
    entries: list[dict[str, Any]],
    *,
    settings: dict[str, Any],
    provider: str,
    catalog_kinds: Iterable[str] = ("ai",),
    refresh: bool = False,
    limit: int = 0,
    progress: Progress = print,
) -> dict[str, Any]:
    pending = pending_generated_image_entries(entries, catalog_kinds=catalog_kinds, refresh=refresh)
    if limit > 0:
        pending = pending[:limit]

    generated = 0
    failures: list[str] = []
    for index, entry in enumerate(pending, 1):
        try:
            await generate_entry_image(entry, settings=settings, provider=provider)
            generated += 1
            progress(f"[{index}/{len(pending)}] generated: {entry['name']}")
        except Exception as exc:
            message = f"{entry.get('name')}: {exc}"
            failures.append(message)
            progress(f"[{index}/{len(pending)}] failed: {message}")

    remaining_entries = pending_generated_image_entries(db.all_entries(), catalog_kinds=catalog_kinds, refresh=False)
    return {
        "provider": provider,
        "requested": len(pending),
        "generated": generated,
        "failed": len(failures),
        "failures": failures,
        "remaining": len(remaining_entries),
    }

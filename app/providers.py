from __future__ import annotations

import base64
import json
import re
import time
import uuid
from pathlib import Path
from typing import Any

import httpx

from .db import MEDIA_DIR, utc_now

OPENROUTER_BASE = "https://openrouter.ai/api/v1"
OPENAI_BASE = "https://api.openai.com/v1"
GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"

LORE_SCHEMA = {
    "name": "monster_girl_codex_entry",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "name", "species", "family", "rarity", "danger", "alignment", "origin", "habitat",
            "summary", "lore", "appearance", "physiology", "ecology", "culture", "temperament",
            "abilities", "weaknesses", "aliases", "tags", "image_prompt", "negative_prompt",
            "st_personality", "st_scenario", "st_first_message", "st_example_dialogue"
        ],
        "properties": {
            "name": {"type": "string"},
            "species": {"type": "string"},
            "family": {"type": "string"},
            "rarity": {"type": "string", "enum": ["Common", "Uncommon", "Rare", "Legendary", "Mythic"]},
            "danger": {"type": "integer", "minimum": 0, "maximum": 5},
            "alignment": {"type": "string"},
            "origin": {"type": "string"},
            "habitat": {"type": "string"},
            "summary": {"type": "string"},
            "lore": {"type": "string"},
            "appearance": {"type": "string"},
            "physiology": {"type": "string"},
            "ecology": {"type": "string"},
            "culture": {"type": "string"},
            "temperament": {"type": "string"},
            "abilities": {"type": "array", "items": {"type": "string"}},
            "weaknesses": {"type": "array", "items": {"type": "string"}},
            "aliases": {"type": "array", "items": {"type": "string"}},
            "tags": {"type": "array", "items": {"type": "string"}},
            "image_prompt": {"type": "string"},
            "negative_prompt": {"type": "string"},
            "st_personality": {"type": "string"},
            "st_scenario": {"type": "string"},
            "st_first_message": {"type": "string"},
            "st_example_dialogue": {"type": "string"}
        }
    }
}


def _extract_json(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except Exception:
        match = re.search(r"\{.*\}", text, flags=re.S)
        if not match:
            raise ValueError("Model did not return a JSON object")
        return json.loads(match.group(0))


def _lore_system_prompt() -> str:
    return """You are the senior field editor of an original fantasy bestiary. Create a polished monster-girl codex entry from the user's concept.

Rules:
- The character and species must be fictional and explicitly adult.
- Do not copy prose, setting canon, named characters, or distinctive lore from Monster Girl Encyclopedia or any other franchise.
- You may use public-domain mythology and broad folklore archetypes, but write wholly original lore.
- Keep internal logic coherent: biology, habitat, culture, powers, weaknesses, and behavior must agree.
- The entry should be usable both as an encyclopedia article and as a roleplay character in SillyTavern.
- Avoid empty adjectives. Favor concrete sensory, ecological, and cultural detail.
- The image prompt must describe one clearly adult character, full design, environment, lighting, composition, and important anatomy. Do not include artist names.
- Return only JSON matching the supplied schema."""


async def openrouter_models(api_key: str) -> list[dict[str, Any]]:
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(f"{OPENROUTER_BASE}/models", headers=headers)
        response.raise_for_status()
        data = response.json().get("data", [])
    models = []
    for model in data:
        models.append({
            "id": model.get("id"),
            "name": model.get("name") or model.get("id"),
            "context_length": model.get("context_length"),
            "pricing": model.get("pricing", {}),
            "architecture": model.get("architecture", {}),
        })
    return models


async def generate_lore(*, api_key: str, model: str, concept: str, world: str = "", tone: str = "", mature: bool = False, temperature: float = 0.85) -> dict[str, Any]:
    if not api_key:
        raise ValueError("OpenRouter API key is required")
    user_prompt = f"""Create a new codex entry.

Core concept:
{concept.strip()}

World or continuity notes:
{world.strip() or 'Original dark-fantasy world; invent compatible details.'}

Desired tone:
{tone.strip() or 'lush field-guide prose, mysterious but readable'}

Content rating:
{'Mature themes are allowed, but keep all characters unambiguously adult and avoid explicit sexual acts in the encyclopedia prose.' if mature else 'SFW / suggestive at most.'}

Generate a complete entry and roleplay fields."""
    payload: dict[str, Any] = {
        "model": model,
        "temperature": temperature,
        "messages": [
            {"role": "system", "content": _lore_system_prompt()},
            {"role": "user", "content": user_prompt},
        ],
        "response_format": {"type": "json_schema", "json_schema": LORE_SCHEMA},
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "http://localhost:17373",
        "X-OpenRouter-Title": "Monstrum Codex Infinite",
    }
    async with httpx.AsyncClient(timeout=180) as client:
        response = await client.post(f"{OPENROUTER_BASE}/chat/completions", headers=headers, json=payload)
        if response.status_code >= 400:
            # Some providers do not support json_schema. Retry with plain JSON mode.
            fallback = dict(payload)
            fallback["response_format"] = {"type": "json_object"}
            response = await client.post(f"{OPENROUTER_BASE}/chat/completions", headers=headers, json=fallback)
        response.raise_for_status()
        body = response.json()
    content = body["choices"][0]["message"]["content"]
    if isinstance(content, list):
        content = "".join(part.get("text", "") if isinstance(part, dict) else str(part) for part in content)
    entry = _extract_json(str(content))
    entry.update({
        "adult": True,
        "rating": "Mature" if mature else "SFW",
        "catalog_kind": "ai",
        "source_kind": "ai",
        "source_name": f"OpenRouter · {model}",
        "extra": {
            "generation": {
                "provider": "openrouter",
                "model": model,
                "created_at": utc_now(),
                "usage": body.get("usage", {}),
            }
        },
    })
    return entry


def _save_image_bytes(raw: bytes, ext: str = "png", prefix: str = "generated") -> str:
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    ext = ext.lower().replace("jpeg", "jpg")
    name = f"{prefix}-{int(time.time())}-{uuid.uuid4().hex[:8]}.{ext}"
    path = MEDIA_DIR / name
    path.write_bytes(raw)
    return f"/media/{name}"


async def generate_openai_image(*, api_key: str, model: str, prompt: str, size: str = "1024x1536", quality: str = "high", background: str = "opaque") -> dict[str, Any]:
    if not api_key:
        raise ValueError("OpenAI API key is required")
    payload = {
        "model": model or "gpt-image-2",
        "prompt": prompt,
        "size": size,
        "quality": quality,
        "background": background,
        "output_format": "png",
        "n": 1,
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=300) as client:
        response = await client.post(f"{OPENAI_BASE}/images/generations", headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()
    item = data["data"][0]
    if item.get("b64_json"):
        raw = base64.b64decode(item["b64_json"])
    elif item.get("url"):
        async with httpx.AsyncClient(timeout=180) as client:
            raw = (await client.get(item["url"])).content
    else:
        raise ValueError("OpenAI returned no image data")
    return {"image_path": _save_image_bytes(raw, "png", "openai"), "provider": "openai", "model": payload["model"]}


def _find_image_block(value: Any) -> dict[str, Any] | None:
    """Find an inline or URI image in either Interactions or legacy Gemini responses."""
    if isinstance(value, dict):
        inline = value.get("inlineData") or value.get("inline_data")
        if isinstance(inline, dict) and (inline.get("data") or inline.get("uri")):
            return inline
        if value.get("type") == "image" and (value.get("data") or value.get("uri")):
            return value
        output_image = value.get("output_image")
        if isinstance(output_image, dict) and (output_image.get("data") or output_image.get("uri")):
            return output_image
        for child in value.values():
            found = _find_image_block(child)
            if found:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _find_image_block(child)
            if found:
                return found
    return None


async def generate_gemini_image(*, api_key: str, model: str, prompt: str, aspect_ratio: str = "2:3", image_size: str = "2K") -> dict[str, Any]:
    if not api_key:
        raise ValueError("Google Gemini API key is required")
    model = model or "gemini-3.1-flash-image"
    payload = {
        "model": model,
        "input": prompt,
        "response_format": {
            "type": "image",
            "mime_type": "image/jpeg",
            "aspect_ratio": aspect_ratio,
            "image_size": image_size,
            "delivery": "inline",
        },
    }
    headers = {"x-goog-api-key": api_key, "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=300, follow_redirects=True) as client:
        response = await client.post(f"{GEMINI_BASE}/interactions", headers=headers, json=payload)
        response.raise_for_status()
        body = response.json()
        image = _find_image_block(body)
        if not image:
            raise ValueError("Gemini returned no image data")
        mime = image.get("mime_type") or image.get("mimeType") or "image/jpeg"
        ext = mime.split("/")[-1].replace("jpeg", "jpg")
        if image.get("data"):
            raw = base64.b64decode(image["data"])
        elif image.get("uri"):
            download = await client.get(image["uri"])
            download.raise_for_status()
            raw = download.content
        else:
            raise ValueError("Gemini returned an empty image block")
    return {"image_path": _save_image_bytes(raw, ext, "gemini"), "provider": "gemini", "model": model}


def _replace_workflow_values(value: Any, replacements: dict[str, Any]) -> Any:
    if isinstance(value, dict):
        return {k: _replace_workflow_values(v, replacements) for k, v in value.items()}
    if isinstance(value, list):
        return [_replace_workflow_values(v, replacements) for v in value]
    if isinstance(value, str):
        if value in replacements:
            return replacements[value]
        for token, replacement in replacements.items():
            value = value.replace(token, str(replacement))
        return value
    return value


async def generate_comfy_image(*, base_url: str, workflow: dict[str, Any], prompt: str, negative_prompt: str = "", width: int = 832, height: int = 1216, seed: int = -1, timeout_seconds: int = 300) -> dict[str, Any]:
    if not base_url:
        base_url = "http://127.0.0.1:8188"
    base_url = base_url.rstrip("/")
    if seed < 0:
        seed = int.from_bytes(uuid.uuid4().bytes[:8], "big") % 2_147_483_647
    cooked = _replace_workflow_values(workflow, {
        "{{PROMPT}}": prompt,
        "{{NEGATIVE_PROMPT}}": negative_prompt,
        "{{WIDTH}}": width,
        "{{HEIGHT}}": height,
        "{{SEED}}": seed,
    })
    client_id = uuid.uuid4().hex
    async with httpx.AsyncClient(timeout=30) as client:
        queued = await client.post(f"{base_url}/prompt", json={"prompt": cooked, "client_id": client_id})
        queued.raise_for_status()
        prompt_id = queued.json().get("prompt_id")
    if not prompt_id:
        raise ValueError("ComfyUI did not return a prompt_id")

    deadline = time.time() + timeout_seconds
    history: dict[str, Any] = {}
    while time.time() < deadline:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(f"{base_url}/history/{prompt_id}")
            response.raise_for_status()
            history = response.json()
        if prompt_id in history:
            break
        await _sleep(1.0)
    else:
        raise TimeoutError("ComfyUI generation timed out")

    outputs = history[prompt_id].get("outputs", {})
    for node in outputs.values():
        for image in node.get("images", []):
            params = {
                "filename": image["filename"],
                "subfolder": image.get("subfolder", ""),
                "type": image.get("type", "output"),
            }
            async with httpx.AsyncClient(timeout=120) as client:
                response = await client.get(f"{base_url}/view", params=params)
                response.raise_for_status()
                raw = response.content
            suffix = Path(image["filename"]).suffix.lstrip(".") or "png"
            return {
                "image_path": _save_image_bytes(raw, suffix, "comfy"),
                "provider": "comfyui",
                "model": "workflow",
                "prompt_id": prompt_id,
                "seed": seed,
            }
    raise ValueError("ComfyUI workflow completed without an image output")


async def _sleep(seconds: float) -> None:
    import asyncio
    await asyncio.sleep(seconds)

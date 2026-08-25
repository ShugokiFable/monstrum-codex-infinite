from __future__ import annotations

import base64
import io
import json
import zipfile
from typing import Any

from PIL import Image, PngImagePlugin


def entry_to_ccv3(entry: dict[str, Any]) -> dict[str, Any]:
    lorebook = {
        "name": f"{entry['name']} Codex Lore",
        "description": f"Embedded lore for {entry['name']}",
        "scan_depth": 4,
        "token_budget": 2048,
        "recursive_scanning": False,
        "extensions": {},
        "entries": [
            {
                "keys": list(dict.fromkeys([entry["name"], entry.get("species", ""), *entry.get("aliases", [])])),
                "secondary_keys": entry.get("tags", []),
                "content": _lorebook_content(entry),
                "enabled": True,
                "insertion_order": 100,
                "case_sensitive": False,
                "use_regex": False,
                "constant": False,
                "selective": False,
                "position": "before_char",
                "extensions": {"monstrum_codex": {"entry_id": entry.get("id")}},
            }
        ],
    }
    return {
        "spec": "chara_card_v3",
        "spec_version": "3.0",
        "data": {
            "name": entry["name"],
            "description": _description(entry),
            "personality": entry.get("st_personality") or entry.get("temperament", ""),
            "scenario": entry.get("st_scenario") or f"{{{{user}}}} encounters {entry['name']} in {entry.get('habitat') or 'the wilds'}.",
            "first_mes": entry.get("st_first_message") or f"*{entry['name']} watches from the edge of the path, waiting to see what {{{{user}}}} will do.*",
            "mes_example": entry.get("st_example_dialogue") or "",
            "creator_notes": "Generated/exported by Monstrum Codex Infinite. Character is an adult fictional being.",
            "system_prompt": "Roleplay only as {{char}}. Never decide {{user}}'s words, thoughts, or actions. Maintain the codex lore and behavioral consistency.",
            "post_history_instructions": "Preserve {{char}}'s species traits, motives, limits, and voice. Progress scenes naturally without controlling {{user}}.",
            "alternate_greetings": [],
            "tags": list(dict.fromkeys([entry.get("family", ""), entry.get("species", ""), *entry.get("tags", [])])),
            "creator": "Monstrum Codex Infinite",
            "character_version": "1.0",
            "extensions": {
                "monstrum_codex": {
                    "entry_id": entry.get("id"),
                    "slug": entry.get("slug"),
                    "rating": entry.get("rating"),
                    "source": entry.get("source_name"),
                }
            },
            "character_book": lorebook,
            "assets": [],
            "nickname": entry["name"],
            "creator_notes_multilingual": {},
            "source": [],
            "group_only_greetings": [],
        },
    }


def _description(entry: dict[str, Any]) -> str:
    fields = [
        ("Species", entry.get("species")),
        ("Appearance", entry.get("appearance")),
        ("Physiology", entry.get("physiology")),
        ("Temperament", entry.get("temperament")),
        ("Abilities", "; ".join(entry.get("abilities", []))),
        ("Weaknesses", "; ".join(entry.get("weaknesses", []))),
        ("Lore", entry.get("lore")),
    ]
    return "\n\n".join(f"{label}: {value}" for label, value in fields if value)


def _lorebook_content(entry: dict[str, Any]) -> str:
    bits = [
        entry.get("summary", ""),
        entry.get("lore", ""),
        f"Habitat: {entry.get('habitat', '')}",
        f"Ecology: {entry.get('ecology', '')}",
        f"Culture: {entry.get('culture', '')}",
        f"Abilities: {', '.join(entry.get('abilities', []))}",
        f"Weaknesses: {', '.join(entry.get('weaknesses', []))}",
    ]
    return "\n\n".join(x for x in bits if x and not x.endswith(": "))


def entry_to_lorebook(entry: dict[str, Any]) -> dict[str, Any]:
    card = entry_to_ccv3(entry)
    return card["data"]["character_book"]


def ccv3_png(card: dict[str, Any], avatar_bytes: bytes | None = None) -> bytes:
    if avatar_bytes:
        try:
            image = Image.open(io.BytesIO(avatar_bytes)).convert("RGBA")
        except Exception:
            image = _placeholder_image(card["data"]["name"])
    else:
        image = _placeholder_image(card["data"]["name"])
    image.thumbnail((1024, 1536))
    info = PngImagePlugin.PngInfo()
    encoded = base64.b64encode(json.dumps(card, ensure_ascii=False).encode("utf-8")).decode("ascii")
    info.add_text("chara", encoded)
    info.add_text("ccv3", encoded)
    out = io.BytesIO()
    image.save(out, format="PNG", pnginfo=info)
    return out.getvalue()


def _placeholder_image(name: str) -> Image.Image:
    image = Image.new("RGBA", (768, 1152), (12, 10, 20, 255))
    # Deliberately simple; the app UI is expected to supply generated art later.
    return image


def charx_bytes(card: dict[str, Any], avatar_bytes: bytes | None = None) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("card.json", json.dumps(card, ensure_ascii=False, indent=2))
        zf.writestr("assets/icon.png", ccv3_png(card, avatar_bytes))
    return out.getvalue()

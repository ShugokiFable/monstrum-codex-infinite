from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app import db  # noqa: E402
from app.ai_media import (  # noqa: E402
    SUPPORTED_BATCH_PROVIDERS,
    generate_missing_entry_images,
    pending_generated_image_entries,
    provider_requirements,
)


def _catalog_kinds(raw: str) -> tuple[str, ...]:
    values = tuple(dict.fromkeys(part.strip().lower() for part in raw.split(",") if part.strip().lower() in {"ai", "user"}))
    return values or ("ai",)


async def run(provider: str, kinds: tuple[str, ...], limit: int, refresh: bool, yes_hosted: bool) -> int:
    db.init_db()
    settings = db.get_setting("ui", {}) or {}
    if provider == "default":
        provider = str(settings.get("defaultImageProvider") or "comfyui").strip().lower()
    if provider not in SUPPORTED_BATCH_PROVIDERS:
        print("Batch generation requires comfyui, openai, or gemini. Manual subscription handoff cannot be automated.")
        return 2

    ready, requirement = provider_requirements(settings, provider)
    if not ready:
        print(f"Missing {requirement}. Open Settings in the app, configure it, and save Settings first.")
        return 2

    entries = db.all_entries()
    pending = pending_generated_image_entries(entries, catalog_kinds=kinds, refresh=refresh)
    selected = pending[:limit] if limit > 0 else pending
    print(f"Libraries: {', '.join(kinds)}. Missing images: {len(pending)}. Images selected this run: {len(selected)}.")
    print(f"Provider: {provider}.")
    if not selected:
        print("Nothing needs an image.")
        return 0

    if provider in {"openai", "gemini"} and not yes_hosted:
        print("Hosted API generation can create billable usage.")
        if not sys.stdin.isatty():
            print("Rerun with --yes-hosted after reviewing the selected count.")
            return 2
        answer = input(f"Type GENERATE to create {len(selected)} billable image request(s): ").strip()
        if answer != "GENERATE":
            print("Cancelled.")
            return 2

    result = await generate_missing_entry_images(
        entries,
        settings=settings,
        provider=provider,
        catalog_kinds=kinds,
        refresh=refresh,
        limit=limit,
        progress=print,
    )
    report_path = db.USERDATA / "ai-image-generation-report.txt"
    report_path.write_text(
        "Monstrum Codex Infinite AI/User image generation report\n"
        f"Provider: {provider}\n"
        f"Libraries: {', '.join(kinds)}\n"
        f"Requested: {result['requested']}\n"
        f"Generated: {result['generated']}\n"
        f"Failed: {result['failed']}\n"
        f"Remaining without local art: {result['remaining']}\n\n"
        + ("\n".join(result["failures"]) if result["failures"] else "No failures."),
        encoding="utf-8",
    )
    print(
        f"Finished. Generated {result['generated']}/{result['requested']}; "
        f"failed {result['failed']}; remaining {result['remaining']}."
    )
    print(f"Report: {report_path}")
    return 0 if result["failed"] == 0 else 2


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate missing AI/User entry portraits with the saved image provider settings.")
    parser.add_argument("--provider", choices=("default", "comfyui", "openai", "gemini"), default="default")
    parser.add_argument("--kinds", default="ai", help="Comma-separated libraries: ai,user")
    parser.add_argument("--limit", type=int, default=10, help="Maximum images this run; use 0 for all")
    parser.add_argument("--refresh", action="store_true", help="Regenerate entries that already have local art")
    parser.add_argument("--yes-hosted", action="store_true", help="Acknowledge possible OpenAI/Gemini API charges")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(run(args.provider, _catalog_kinds(args.kinds), max(args.limit, 0), args.refresh, args.yes_hosted)))


if __name__ == "__main__":
    main()

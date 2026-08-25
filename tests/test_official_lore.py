"""Regression: official entries with cached wiki lore must exist and read as
real prose (>=200 chars, no Cloudflare stub). Run: python tests/test_official_lore.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import db  # noqa: E402


def main() -> int:
    with db.connection() as con:
        total, with_text = con.execute(
            "select count(*), sum(case when coalesce(lore,'')!='' then 1 else 0 end) "
            "from entries where catalog_kind='official'"
        ).fetchone()
    print(f"officials: {total}, with real lore text: {with_text}")
    assert (with_text or 0) > 0, "no official entry has cached article text yet"

    items, _ = db.list_entries(catalog_kind="official", limit=2000)
    filled = [e for e in items if (e.get("lore") or "").strip()]
    sample = min(filled, key=lambda e: len(e["lore"]))
    text = sample["lore"].lower()
    assert len(sample["lore"]) >= 200, f"shortest cached lore too short: {len(sample['lore'])}"
    for marker in ("just a moment", "enable javascript", "performing security verification"):
        assert marker not in text, f"challenge-page text leaked into lore of {sample['name']}"
    print(f"sample OK: {sample['name']} -> {len(sample['lore'])} chars of real prose")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

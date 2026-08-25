from __future__ import annotations

import json
import re
import sqlite3
import sys
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

RESOURCE_ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
APP_ROOT = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[1]
USERDATA = APP_ROOT / "userdata"
DB_PATH = USERDATA / "codex.sqlite3"
SEED_PATH = RESOURCE_ROOT / "data" / "seed_codex.json"
OFFICIAL_SEED_PATH = RESOURCE_ROOT / "data" / "official_catalog.json"
MEDIA_DIR = USERDATA / "media"

_LOCK = threading.RLock()
VALID_CATALOG_KINDS = {"official", "ai", "user"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def slugify(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-") or "entry"


def _connect() -> sqlite3.Connection:
    USERDATA.mkdir(parents=True, exist_ok=True)
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    return con


@contextmanager
def connection():
    with _LOCK:
        con = _connect()
        try:
            yield con
            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()


def _table_columns(con: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in con.execute(f"PRAGMA table_info({table})")}


def _migrate(con: sqlite3.Connection) -> None:
    columns = _table_columns(con, "entries")
    if "catalog_kind" not in columns:
        con.execute("ALTER TABLE entries ADD COLUMN catalog_kind TEXT NOT NULL DEFAULT 'user'")
    if "image_url" not in columns:
        con.execute("ALTER TABLE entries ADD COLUMN image_url TEXT NOT NULL DEFAULT ''")

    # The original bundled foundation was machine-authored original prose, so keep it
    # out of the user library when upgrading an existing installation.
    con.execute(
        """
        UPDATE entries
        SET catalog_kind='ai'
        WHERE source_name='Foundational Codex v1'
           OR source_kind IN ('ai', 'public-domain-archetype')
        """
    )
    con.execute("UPDATE entries SET catalog_kind='official' WHERE source_kind='official'")
    con.execute(
        "UPDATE entries SET catalog_kind='user' WHERE catalog_kind NOT IN ('official','ai','user') OR catalog_kind IS NULL OR catalog_kind=''"
    )
    con.execute("CREATE INDEX IF NOT EXISTS idx_entries_catalog_kind ON entries(catalog_kind)")


def _seed_file(con: sqlite3.Connection, path: Path, *, only_missing: bool = False) -> int:
    if not path.exists():
        return 0
    items = json.loads(path.read_text(encoding="utf-8"))
    inserted = 0
    for item in items:
        slug = str(item.get("slug") or slugify(str(item.get("name") or "entry")))
        if only_missing and con.execute("SELECT 1 FROM entries WHERE slug=?", (slug,)).fetchone():
            continue
        try:
            _insert_entry(con, {**item, "slug": slug})
            inserted += 1
        except sqlite3.IntegrityError:
            continue
    return inserted


def init_db() -> None:
    with connection() as con:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                slug TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                species TEXT NOT NULL DEFAULT '',
                family TEXT NOT NULL DEFAULT '',
                rarity TEXT NOT NULL DEFAULT 'Uncommon',
                danger INTEGER NOT NULL DEFAULT 2,
                alignment TEXT NOT NULL DEFAULT 'Unknown',
                origin TEXT NOT NULL DEFAULT '',
                habitat TEXT NOT NULL DEFAULT '',
                summary TEXT NOT NULL DEFAULT '',
                lore TEXT NOT NULL DEFAULT '',
                appearance TEXT NOT NULL DEFAULT '',
                physiology TEXT NOT NULL DEFAULT '',
                ecology TEXT NOT NULL DEFAULT '',
                culture TEXT NOT NULL DEFAULT '',
                temperament TEXT NOT NULL DEFAULT '',
                abilities_json TEXT NOT NULL DEFAULT '[]',
                weaknesses_json TEXT NOT NULL DEFAULT '[]',
                aliases_json TEXT NOT NULL DEFAULT '[]',
                tags_json TEXT NOT NULL DEFAULT '[]',
                image_prompt TEXT NOT NULL DEFAULT '',
                negative_prompt TEXT NOT NULL DEFAULT '',
                image_path TEXT NOT NULL DEFAULT '',
                image_url TEXT NOT NULL DEFAULT '',
                catalog_kind TEXT NOT NULL DEFAULT 'user',
                source_kind TEXT NOT NULL DEFAULT 'user',
                source_name TEXT NOT NULL DEFAULT '',
                source_url TEXT NOT NULL DEFAULT '',
                rating TEXT NOT NULL DEFAULT 'SFW',
                adult INTEGER NOT NULL DEFAULT 1,
                favorite INTEGER NOT NULL DEFAULT 0,
                st_personality TEXT NOT NULL DEFAULT '',
                st_scenario TEXT NOT NULL DEFAULT '',
                st_first_message TEXT NOT NULL DEFAULT '',
                st_example_dialogue TEXT NOT NULL DEFAULT '',
                extra_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_entries_name ON entries(name COLLATE NOCASE);
            CREATE INDEX IF NOT EXISTS idx_entries_family ON entries(family COLLATE NOCASE);
            CREATE INDEX IF NOT EXISTS idx_entries_habitat ON entries(habitat COLLATE NOCASE);
            CREATE INDEX IF NOT EXISTS idx_entries_favorite ON entries(favorite);
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value_json TEXT NOT NULL
            );
            """
        )
        _migrate(con)
        count = con.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
        if count == 0:
            _seed_file(con, SEED_PATH)
        # The reference index is additive and versioned independently. Existing users
        # receive new official names without losing edits or personal entries.
        _seed_file(con, OFFICIAL_SEED_PATH, only_missing=True)


def _as_json(value: Any, fallback: Any) -> str:
    if value is None:
        value = fallback
    return json.dumps(value, ensure_ascii=False)


def _catalog_kind(src: dict[str, Any]) -> str:
    explicit = str(src.get("catalog_kind") or "").strip().lower()
    if explicit in VALID_CATALOG_KINDS:
        return explicit
    source_kind = str(src.get("source_kind") or "").strip().lower()
    source_name = str(src.get("source_name") or "")
    if source_kind == "official":
        return "official"
    if source_kind in {"ai", "public-domain-archetype"} or source_name == "Foundational Codex v1":
        return "ai"
    return "user"


def normalize_entry(data: dict[str, Any], *, existing: dict[str, Any] | None = None) -> dict[str, Any]:
    src = {**(existing or {}), **data}
    now = utc_now()
    name = str(src.get("name") or "Untitled Creature").strip()
    slug = str(src.get("slug") or slugify(name)).strip()
    catalog_kind = _catalog_kind(src)
    default_source_kind = "official" if catalog_kind == "official" else "ai" if catalog_kind == "ai" else "user"
    return {
        "slug": slug,
        "name": name,
        "species": str(src.get("species") or name),
        "family": str(src.get("family") or "Unclassified"),
        "rarity": str(src.get("rarity") or "Uncommon"),
        "danger": max(0, min(5, int(src.get("danger", 2) or 0))),
        "alignment": str(src.get("alignment") or "Unknown"),
        "origin": str(src.get("origin") or ""),
        "habitat": str(src.get("habitat") or ""),
        "summary": str(src.get("summary") or ""),
        "lore": str(src.get("lore") or ""),
        "appearance": str(src.get("appearance") or ""),
        "physiology": str(src.get("physiology") or ""),
        "ecology": str(src.get("ecology") or ""),
        "culture": str(src.get("culture") or ""),
        "temperament": str(src.get("temperament") or ""),
        "abilities_json": _as_json(src.get("abilities"), []),
        "weaknesses_json": _as_json(src.get("weaknesses"), []),
        "aliases_json": _as_json(src.get("aliases"), []),
        "tags_json": _as_json(src.get("tags"), []),
        "image_prompt": str(src.get("image_prompt") or ""),
        "negative_prompt": str(src.get("negative_prompt") or ""),
        "image_path": str(src.get("image_path") or ""),
        "image_url": str(src.get("image_url") or ""),
        "catalog_kind": catalog_kind,
        "source_kind": str(src.get("source_kind") or default_source_kind),
        "source_name": str(src.get("source_name") or ""),
        "source_url": str(src.get("source_url") or ""),
        "rating": str(src.get("rating") or "SFW"),
        "adult": 1 if bool(src.get("adult", True)) else 0,
        "favorite": 1 if bool(src.get("favorite", False)) else 0,
        "st_personality": str(src.get("st_personality") or ""),
        "st_scenario": str(src.get("st_scenario") or ""),
        "st_first_message": str(src.get("st_first_message") or ""),
        "st_example_dialogue": str(src.get("st_example_dialogue") or ""),
        "extra_json": _as_json(src.get("extra"), {}),
        "created_at": str(src.get("created_at") or now),
        "updated_at": now,
    }


def _insert_entry(con: sqlite3.Connection, data: dict[str, Any]) -> int:
    row = normalize_entry(data)
    cols = ", ".join(row.keys())
    marks = ", ".join(["?"] * len(row))
    cur = con.execute(f"INSERT INTO entries ({cols}) VALUES ({marks})", tuple(row.values()))
    return int(cur.lastrowid)


def create_entry(data: dict[str, Any]) -> dict[str, Any]:
    with connection() as con:
        row = normalize_entry(data)
        base_slug = row["slug"]
        suffix = 2
        while con.execute("SELECT 1 FROM entries WHERE slug=?", (row["slug"],)).fetchone():
            row["slug"] = f"{base_slug}-{suffix}"
            suffix += 1
        cols = ", ".join(row.keys())
        marks = ", ".join(["?"] * len(row))
        cur = con.execute(f"INSERT INTO entries ({cols}) VALUES ({marks})", tuple(row.values()))
        return get_entry(int(cur.lastrowid), con=con)


def _decode(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    item = dict(row)
    for key in ("abilities", "weaknesses", "aliases", "tags"):
        raw = item.pop(f"{key}_json", "[]")
        try:
            item[key] = json.loads(raw)
        except Exception:
            item[key] = []
    raw_extra = item.pop("extra_json", "{}")
    try:
        item["extra"] = json.loads(raw_extra)
    except Exception:
        item["extra"] = {}
    item["adult"] = bool(item.get("adult"))
    item["favorite"] = bool(item.get("favorite"))
    item["catalog_kind"] = item.get("catalog_kind") or _catalog_kind(item)
    return item


def get_entry(entry_id: int, *, con: sqlite3.Connection | None = None) -> dict[str, Any] | None:
    owns = con is None
    con = con or _connect()
    try:
        row = con.execute("SELECT * FROM entries WHERE id=?", (entry_id,)).fetchone()
        return _decode(row) if row else None
    finally:
        if owns:
            con.close()


def update_entry(entry_id: int, data: dict[str, Any]) -> dict[str, Any] | None:
    with connection() as con:
        current = get_entry(entry_id, con=con)
        if not current:
            return None
        row = normalize_entry(data, existing=current)
        pairs = ", ".join(f"{k}=?" for k in row)
        con.execute(f"UPDATE entries SET {pairs} WHERE id=?", (*row.values(), entry_id))
        return get_entry(entry_id, con=con)


def update_entry_fields(entry_id: int, **fields: Any) -> dict[str, Any] | None:
    current = get_entry(entry_id)
    if not current:
        return None
    return update_entry(entry_id, {**current, **fields})


def delete_entry(entry_id: int) -> bool:
    with connection() as con:
        cur = con.execute("DELETE FROM entries WHERE id=?", (entry_id,))
        return cur.rowcount > 0


def list_entries(
    query: str = "",
    family: str = "",
    habitat: str = "",
    rarity: str = "",
    favorites: bool = False,
    catalog_kind: str = "",
    sort: str = "name",
    limit: int = 500,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    clauses: list[str] = []
    params: list[Any] = []
    if query:
        q = f"%{query.lower()}%"
        clauses.append("(lower(name) LIKE ? OR lower(species) LIKE ? OR lower(summary) LIKE ? OR lower(tags_json) LIKE ? OR lower(aliases_json) LIKE ?)")
        params.extend([q, q, q, q, q])
    if family:
        clauses.append("family = ?")
        params.append(family)
    if habitat:
        clauses.append("habitat LIKE ?")
        params.append(f"%{habitat}%")
    if rarity:
        clauses.append("rarity = ?")
        params.append(rarity)
    if favorites:
        clauses.append("favorite = 1")
    if catalog_kind in VALID_CATALOG_KINDS:
        clauses.append("catalog_kind = ?")
        params.append(catalog_kind)
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    order_map = {
        "name": "name COLLATE NOCASE ASC",
        "newest": "updated_at DESC",
        "danger": "danger DESC, name COLLATE NOCASE",
        "rarity": "CASE rarity WHEN 'Mythic' THEN 5 WHEN 'Legendary' THEN 4 WHEN 'Rare' THEN 3 WHEN 'Uncommon' THEN 2 ELSE 1 END DESC, name COLLATE NOCASE",
    }
    order = order_map.get(sort, order_map["name"])
    with connection() as con:
        total = con.execute(f"SELECT COUNT(*) FROM entries{where}", params).fetchone()[0]
        rows = con.execute(
            f"SELECT * FROM entries{where} ORDER BY {order} LIMIT ? OFFSET ?",
            (*params, min(limit, 2000), max(offset, 0)),
        ).fetchall()
        return [_decode(row) for row in rows], int(total)


def catalog_counts() -> dict[str, int]:
    counts = {"all": 0, "official": 0, "ai": 0, "user": 0, "favorites": 0}
    with connection() as con:
        counts["all"] = int(con.execute("SELECT COUNT(*) FROM entries").fetchone()[0])
        counts["favorites"] = int(con.execute("SELECT COUNT(*) FROM entries WHERE favorite=1").fetchone()[0])
        for kind, count in con.execute("SELECT catalog_kind, COUNT(*) FROM entries GROUP BY catalog_kind"):
            if kind in counts:
                counts[str(kind)] = int(count)
    return counts


def facets() -> dict[str, Any]:
    with connection() as con:
        families = [r[0] for r in con.execute("SELECT DISTINCT family FROM entries WHERE family<>'' ORDER BY family COLLATE NOCASE")]
        habitats = [r[0] for r in con.execute("SELECT DISTINCT habitat FROM entries WHERE habitat<>'' ORDER BY habitat COLLATE NOCASE")]
        rarities = [r[0] for r in con.execute("SELECT DISTINCT rarity FROM entries WHERE rarity<>'' ORDER BY rarity COLLATE NOCASE")]
    return {"families": families, "habitats": habitats, "rarities": rarities, "catalog_counts": catalog_counts()}


def get_setting(key: str, default: Any = None) -> Any:
    with connection() as con:
        row = con.execute("SELECT value_json FROM settings WHERE key=?", (key,)).fetchone()
    if not row:
        return default
    try:
        return json.loads(row[0])
    except Exception:
        return default


def set_setting(key: str, value: Any) -> None:
    with connection() as con:
        con.execute(
            "INSERT INTO settings(key, value_json) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",
            (key, json.dumps(value, ensure_ascii=False)),
        )


def import_entries(items: Iterable[dict[str, Any]], mode: str = "merge") -> dict[str, int]:
    created = updated = skipped = 0
    with connection() as con:
        for item in items:
            slug = str(item.get("slug") or slugify(str(item.get("name") or "entry")))
            found = con.execute("SELECT id FROM entries WHERE slug=?", (slug,)).fetchone()
            if found and mode == "skip":
                skipped += 1
                continue
            if found:
                current = get_entry(int(found[0]), con=con)
                row = normalize_entry(item, existing=current)
                pairs = ", ".join(f"{k}=?" for k in row)
                con.execute(f"UPDATE entries SET {pairs} WHERE id=?", (*row.values(), int(found[0])))
                updated += 1
            else:
                item = {**item, "slug": slug}
                _insert_entry(con, item)
                created += 1
    return {"created": created, "updated": updated, "skipped": skipped}


def all_entries() -> list[dict[str, Any]]:
    with connection() as con:
        rows = con.execute("SELECT * FROM entries ORDER BY name COLLATE NOCASE").fetchall()
        return [_decode(row) for row in rows]

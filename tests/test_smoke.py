from __future__ import annotations

import base64
import asyncio
import io
import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from app import db
from app.ai_media import build_entry_image_prompt, pending_generated_image_entries, provider_requirements
from app.browser_official_cache import BrowserRecord, BrowserSession, _acquire_live_page, _collapse_to_single_page, _extract_primary_entry_record, _goto_with_response, _same_wiki_target, match_browser_record, match_profile_records, pending_portrait_entries
from app.exports import ccv3_png, entry_to_ccv3, entry_to_lorebook
from app.main import app
from app.official_media import classify_profile_filename, official_media_manifest, pending_media_entries
from app.official_sources import official_browser_image_candidates, official_browser_mugshot_candidates, official_filename_stems
from app.providers import _find_image_block
from fastapi.testclient import TestClient


class SmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db.init_db()
        cls.client = TestClient(app)

    def test_seed_count(self):
        counts = db.catalog_counts()
        self.assertGreaterEqual(counts["all"], 496)
        self.assertEqual(counts["official"], 237)
        self.assertGreaterEqual(counts["ai"], 259)

    def test_catalog_separation(self):
        official, official_total = db.list_entries(catalog_kind="official", limit=1000)
        ai, ai_total = db.list_entries(catalog_kind="ai", limit=1000)
        self.assertEqual(official_total, 237)
        self.assertTrue(all(item["catalog_kind"] == "official" for item in official))
        self.assertGreaterEqual(ai_total, 259)
        self.assertTrue(all(item["catalog_kind"] == "ai" for item in ai))

    def test_search(self):
        items, total = db.list_entries(query="dragoness")
        self.assertGreaterEqual(total, 1)
        self.assertTrue(any("Dragoness" in x["name"] for x in items))

    def test_ccv3_exports(self):
        item = db.all_entries()[0]
        card = entry_to_ccv3(item)
        self.assertEqual(card["spec"], "chara_card_v3")
        self.assertIn("character_book", card["data"])
        lore = entry_to_lorebook(item)
        self.assertTrue(lore["entries"])
        png = ccv3_png(card)
        image = Image.open(io.BytesIO(png))
        self.assertIn("chara", image.info)
        decoded = json.loads(base64.b64decode(image.info["chara"]))
        self.assertEqual(decoded["data"]["name"], item["name"])

    def test_api_and_frontend(self):
        health = self.client.get("/api/health")
        self.assertEqual(health.status_code, 200)
        self.assertTrue(health.json()["ok"])
        front = self.client.get("/")
        self.assertEqual(front.status_code, 200)
        self.assertIn("Monstrum Codex Infinite", front.text)
        found = self.client.get("/api/entries", params={"query": "lamia", "limit": 3})
        self.assertEqual(found.status_code, 200)
        self.assertGreaterEqual(found.json()["total"], 1)

    def test_entry_crud(self):
        created = self.client.post("/api/entries", json={"data": {
            "name": "Test Glasswing",
            "family": "Insectoid",
            "summary": "Temporary automated test entry.",
            "adult": True,
        }})
        self.assertEqual(created.status_code, 200)
        item = created.json()
        entry_id = item["id"]
        try:
            changed = self.client.put(f"/api/entries/{entry_id}", json={"data": {**item, "rarity": "Rare"}})
            self.assertEqual(changed.status_code, 200)
            self.assertEqual(changed.json()["rarity"], "Rare")
        finally:
            removed = self.client.delete(f"/api/entries/{entry_id}")
            self.assertEqual(removed.status_code, 200)

    def test_v1_database_migration(self):
        import sqlite3
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "old.sqlite3"
            con = sqlite3.connect(path)
            con.execute("CREATE TABLE entries (id INTEGER PRIMARY KEY, source_name TEXT, source_kind TEXT)")
            con.execute("INSERT INTO entries(source_name, source_kind) VALUES (?, ?)", ("Foundational Codex v1", "public-domain-archetype"))
            db._migrate(con)
            columns = {row[1] for row in con.execute("PRAGMA table_info(entries)")}
            kind = con.execute("SELECT catalog_kind FROM entries").fetchone()[0]
            con.close()
            self.assertIn("catalog_kind", columns)
            self.assertIn("image_url", columns)
            self.assertEqual(kind, "ai")


    def test_official_image_candidates(self):
        entry = {
            "id": 42,
            "name": "Aka-Oni",
            "catalog_kind": "official",
            "image_url": "",
            "extra": {"official_page_title": "Aka-Oni"},
        }
        stems = official_filename_stems(entry)
        candidates = official_browser_image_candidates(entry)
        self.assertIn("AkaOni", stems)
        self.assertTrue(any("AkaOniMug.png" in url for url in candidates))
        self.assertTrue(all(url.startswith("https://") for url in candidates))

    def test_frontend_contains_real_browser_cache(self):
        front = self.client.get("/")
        self.assertEqual(front.status_code, 200)
        script = self.client.get("/assets/app.js")
        self.assertEqual(script.status_code, 200)
        self.assertIn("cache-browser-launch", script.text)
        self.assertIn("data-image-queue", script.text)
        status = self.client.get("/api/official/cache-browser-status")
        self.assertEqual(status.status_code, 200)
        self.assertEqual(status.json()["total"], 237)

    def test_live_category_filename_matching(self):
        entries, _ = db.list_entries(catalog_kind="official", limit=1000)
        abaddon = next(item for item in entries if item["name"] == "Abaddon")
        folk = next(item for item in entries if item["name"] == "Abaddon Folk")
        records = [
            BrowserRecord("AbaddonFolkMug.png", "https://mgewiki.moe/index.php/File:AbaddonFolkMug.png", "", "mugshot"),
            BrowserRecord("AbaddonMug.png", "https://mgewiki.moe/index.php/File:AbaddonMug.png", "", "mugshot"),
            BrowserRecord("Abaddon eng1.png", "https://mgewiki.moe/index.php/File:Abaddon_eng1.png", "", "profile"),
        ]
        self.assertEqual(match_browser_record(abaddon, records).filename, "AbaddonMug.png")
        self.assertEqual(match_browser_record(folk, records).filename, "AbaddonFolkMug.png")

    def test_mugshot_candidates_exclude_profile_sheets(self):
        entry = {
            "name": "Alraune",
            "image_url": "https://mgewiki.moe/images/a/al/Alraune_eng1.png",
            "extra": {"official_page_title": "Alraune", "official_image_category": "profile", "official_image_filename": "Alraune eng1.png"},
        }
        candidates = official_browser_mugshot_candidates(entry)
        self.assertTrue(candidates)
        self.assertTrue(all("Mug" in candidate for candidate in candidates))
        self.assertTrue(all("eng1" not in candidate for candidate in candidates))

    def test_old_profile_scan_is_automatically_pending_for_repair(self):
        path = db.MEDIA_DIR / "test-old-profile-sheet.png"
        Image.new("RGB", (800, 1200), "white").save(path)
        try:
            entry = {
                "name": "Alraune",
                "image_path": f"/media/{path.name}",
                "extra": {"official_image_category": "profile", "official_image_filename": "Alraune eng1.png"},
            }
            self.assertEqual(pending_portrait_entries([entry], False), [entry])
            entry["extra"] = {"official_image_category": "mugshot", "official_image_filename": "AlrauneMug.jpg"}
            # A v1.1.5 mugshot alone is still pending because v1.1.7 must index
            # standalone portraits and entry pages into the media manifest.
            self.assertEqual(pending_portrait_entries([entry], False), [entry])
        finally:
            path.unlink(missing_ok=True)

    def test_frontend_uses_multi_asset_official_layout(self):
        script = self.client.get("/assets/app.js").text
        css = self.client.get("/assets/app.css").text
        front = self.client.get("/").text
        self.assertIn("officialMediaSection", script)
        self.assertIn("entryImages", script)
        self.assertIn("official-full-portrait", css)
        self.assertIn("official-media-strip", css)
        self.assertIn("officialMediaDialog", front)

    def test_profile_category_classification(self):
        entry = {"name": "Apsara", "aliases": [], "extra": {"official_page_title": "Apsara"}}
        portrait = classify_profile_filename(entry, "Apsara_0.jpg")
        english = classify_profile_filename(entry, "Apsara eng1.png")
        japanese = classify_profile_filename(entry, "Apsara_jp2.png")
        wrong = classify_profile_filename(entry, "Apsara Folk_0.jpg")
        self.assertEqual(portrait["kind"], "portrait")
        self.assertEqual(portrait["index"], 0)
        self.assertEqual(english["language"], "en")
        self.assertEqual(english["index"], 1)
        self.assertEqual(japanese["language"], "jp")
        self.assertIsNone(wrong)

    def test_profile_records_include_all_portraits_and_entry_pages(self):
        entry = {"name": "Apsara", "aliases": [], "extra": {"official_page_title": "Apsara"}}
        records = [
            BrowserRecord("Apsara_2.jpg", "file:2", "", "profile"),
            BrowserRecord("Apsara eng2.png", "file:eng2", "", "profile"),
            BrowserRecord("Apsara_0.jpg", "file:0", "", "profile"),
            BrowserRecord("Apsara eng1.png", "file:eng1", "", "profile"),
            BrowserRecord("ApsaraMug.jpg", "file:mug", "", "mugshot"),
        ]
        matched = match_profile_records(entry, records)
        self.assertEqual([x.filename for x in matched["portraits"]], ["Apsara_0.jpg", "Apsara_2.jpg"])
        self.assertEqual([x.filename for x in matched["entry_images"]], ["Apsara eng1.png", "Apsara eng2.png"])

    def test_complete_manifest_skips_incremental_cache(self):
        names = ["test-manifest-mug.jpg", "test-manifest-portrait.jpg", "test-manifest-entry.png"]
        try:
            for name in names:
                Image.new("RGB", (64, 64), "white").save(db.MEDIA_DIR / name)
            entry = {
                "name": "Apsara",
                "image_path": f"/media/{names[0]}",
                "extra": {"official_media": {
                    "schema": 3,
                    "complete": True,
                    "failures": [],
                    "mugshot": {"path": f"/media/{names[0]}", "filename": "ApsaraMug.jpg"},
                    "portraits": [{"path": f"/media/{names[1]}", "filename": "Apsara_0.jpg"}],
                    "entry_images": [{"path": f"/media/{names[2]}", "filename": "Apsara eng1.png"}],
                }},
            }
            self.assertEqual(pending_media_entries([entry], False), [])
            manifest = official_media_manifest(entry)
            self.assertEqual(len(manifest["portraits"]), 1)
            self.assertEqual(len(manifest["entry_images"]), 1)
        finally:
            for name in names:
                (db.MEDIA_DIR / name).unlink(missing_ok=True)

    def test_mediawiki_category_url_equivalence(self):
        query = "https://mgewiki.moe/index.php?title=Category%3AProfile_Image"
        pretty = "https://mgewiki.moe/index.php/Category:Profile_Image"
        homepage = "https://mgewiki.moe/"
        self.assertTrue(_same_wiki_target(query, pretty))
        self.assertFalse(_same_wiki_target(homepage, query))

    def test_browser_startup_tabs_collapse_to_one(self):
        class FakePage:
            def __init__(self):
                self.closed = False

            def is_closed(self):
                return self.closed

            async def close(self):
                self.closed = True

        class FakeContext:
            def __init__(self):
                self.pages = [FakePage(), FakePage(), FakePage()]

            async def new_page(self):
                page = FakePage()
                self.pages.append(page)
                return page

        context = FakeContext()
        controlled = asyncio.run(_collapse_to_single_page(context, lambda _: None))
        self.assertIs(controlled, context.pages[0])
        self.assertFalse(controlled.closed)
        self.assertTrue(all(page.closed for page in context.pages[1:]))


    def test_dead_startup_page_is_reacquired(self):
        class FakePage:
            def __init__(self, closed=False):
                self.closed = closed

            def is_closed(self):
                return self.closed

        class FakeContext:
            def __init__(self):
                self.pages = [FakePage(False)]

            async def new_page(self):
                page = FakePage(False)
                self.pages.append(page)
                return page

        dead = FakePage(True)
        context = FakeContext()
        session = BrowserSession(context, dead, dead, Path("msedge.exe"), object())
        recovered = asyncio.run(_acquire_live_page(session, lambda _: None))
        self.assertIs(recovered, context.pages[0])
        self.assertIs(session.index_page, recovered)
        self.assertIs(session.download_page, recovered)


    def test_navigation_recovers_from_closed_startup_page(self):
        class FakeResponse:
            status = 200

        class FakePage:
            def __init__(self, fail=False):
                self.fail = fail
                self.closed = False
                self.url = "about:blank"

            def is_closed(self):
                return self.closed

            async def bring_to_front(self):
                return None

            async def goto(self, target, **kwargs):
                if self.fail:
                    self.closed = True
                    raise RuntimeError("Target page, context or browser has been closed")
                self.url = target
                return FakeResponse()

            async def close(self):
                self.closed = True

        class FakeContext:
            def __init__(self):
                self.pages = []

            async def new_page(self):
                page = FakePage(False)
                self.pages.append(page)
                return page

        context = FakeContext()
        dead = FakePage(True)
        context.pages.append(dead)
        session = BrowserSession(context, dead, dead, Path("msedge.exe"), object())
        page, response = asyncio.run(_goto_with_response(session, "https://mgewiki.moe/test", lambda _: None, timeout=1000))
        self.assertFalse(page.is_closed())
        self.assertEqual(page.url, "https://mgewiki.moe/test")
        self.assertEqual(response.status, 200)
        self.assertIs(session.index_page, page)


    def test_compact_and_unnumbered_portrait_filenames(self):
        aka = {"name": "Aka-Oni", "species": "Aka-Oni", "aliases": [], "extra": {"official_page_title": "Aka-Oni"}}
        alraune = {"name": "Alraune", "species": "Alraune", "aliases": [], "extra": {"official_page_title": "Alraune"}}
        compact = classify_profile_filename(aka, "AkaOni0.jpg")
        unnumbered = classify_profile_filename(alraune, "Alraune.jpg")
        self.assertEqual(compact["kind"], "portrait")
        self.assertEqual(compact["index"], 0)
        self.assertEqual(unnumbered["kind"], "portrait")

    def test_frontend_official_cards_have_local_fallback_chain(self):
        script = self.client.get("/assets/app.js").text
        self.assertIn("media.portraits.forEach(asset => push(assetSrc(asset), 'portrait'))", script)
        self.assertIn("media.entryImages.forEach(asset => push(assetSrc(asset), 'entry'))", script)
        self.assertIn("official-entry-page", script)

    def test_entry_page_primary_image_fallback(self):
        class FakePage:
            async def evaluate(self, script):
                return {
                    "href": "https://mgewiki.moe/index.php/File:AkaOniMug.jpg",
                    "title": "File:AkaOniMug.jpg",
                    "preview": "https://mgewiki.moe/images/a/aa/AkaOniMug.jpg",
                }

        record = asyncio.run(_extract_primary_entry_record(FakePage()))
        self.assertEqual(record.filename, "AkaOniMug.jpg")
        self.assertEqual(record.category, "mugshot-page")

    def test_gemini_response_shapes(self):
        interactions = {"steps": [{"type": "model_output", "content": [{"type": "image", "data": "AA==", "mime_type": "image/jpeg"}]}]}
        direct = {"output_image": {"data": "AA==", "mime_type": "image/png"}}
        legacy = {"candidates": [{"content": {"parts": [{"inlineData": {"data": "AA==", "mimeType": "image/png"}}]}}]}
        self.assertEqual(_find_image_block(interactions)["data"], "AA==")
        self.assertEqual(_find_image_block(direct)["mime_type"], "image/png")
        self.assertEqual(_find_image_block(legacy)["data"], "AA==")

    def test_ai_entries_are_not_official_cache_targets(self):
        entries, _ = db.list_entries(catalog_kind="ai", limit=1000)
        aello = next(item for item in entries if item["name"] == "Aello")
        self.assertEqual(aello["catalog_kind"], "ai")
        self.assertFalse(str(aello.get("source_kind") or "").lower() == "official")
        pending = pending_generated_image_entries([aello], catalog_kinds=("ai",))
        self.assertEqual(pending, [aello])
        self.assertIn("adult", build_entry_image_prompt(aello).lower())

    def test_batch_provider_requirements(self):
        self.assertEqual(provider_requirements({}, "openai"), (False, "OpenAI API key"))
        self.assertEqual(provider_requirements({"openaiKey": "test"}, "openai")[0], True)
        self.assertEqual(provider_requirements({"comfyWorkflow": "{}"}, "comfyui")[0], False)
        self.assertEqual(provider_requirements({"comfyWorkflow": '{"1": {"class_type": "SaveImage"}}'}, "comfyui")[0], True)

    def test_frontend_explains_ai_art_and_batch_generation(self):
        front = self.client.get("/").text
        script = self.client.get("/assets/app.js").text
        css = self.client.get("/assets/app.css").text
        self.assertIn("Fill missing AI and user portraits", front)
        self.assertIn("image-batch-launch", script)
        self.assertIn("Generate portrait", script)
        self.assertIn("library-divider", css)
        status = self.client.get("/api/ai/image-batch-status", params={"catalog_kinds": "ai"})
        self.assertEqual(status.status_code, 200)
        self.assertGreaterEqual(status.json()["total"], 259)



if __name__ == "__main__":
    unittest.main()

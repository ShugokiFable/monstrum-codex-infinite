# Monstrum Codex Infinite

A local-first monster-girl encyclopedia and AI creation studio inspired by the workflow strengths of Bionus Grabber: dense browsing, source-aware records, adaptable imports, local caching, and fast inspection. It is not a fork of Grabber and does not reuse its code.

## Included in v1.5.0 — The True Codex

- **Naturalist Profile** on every entry: diet, behavior (cycle / social / disposition / danger response), likes, dislikes, beloved terrain, avoided terrain — derived deterministically from each species' own fields, stable across restarts.
- Double-launch safe: `desktop.py` reuses an already-running instance instead of failing to bind the port.

## Included in v1.4.0 — Living Codex II: Foil & Fire

- **Danger-reactive scenes** — habitat particles burn brighter, denser, and faster on deadlier specimens.
- **Holographic foil rings** — Rare/Mythic/Legendary cards carry a slowly rotating gold-pink-cyan border.
- **Card tilt & hero parallax** — cards lean under the cursor; the detail hero's art, particles, and mist drift at separate depths.
- **Recently Viewed strip** — the last eight specimens you opened, one click away.
- **Keyboard cheatsheet** (`?`) and **heart-bursts** when you favorite a specimen.

## Included in v1.3.0 — The Living Codex

- **Living habitat scenes:** every entry's living space is animated in place. Volcanic lairs glow with rising embers, mountain homes fall with snow, seas and rivers breathe bubbles, forests drift with fireflies, deserts roll with dust, caverns sparkle, cosmic habitats twinkle with stars, and spectral places wander with pale wisps. Scenes render locally on a lightweight canvas engine (no GIFs, no network), pause offscreen and under reduced-motion, and layer under the card and detail hero artwork.
- **Surprise Me** — a topbar dice that opens a random specimen from the current view (`S` key).
- **Prev/next navigation** across the current filtered view, with `←`/`→` arrow keys and `F` to favorite from the detail panel.
- Staggered card entrances, a count-up specimen ticker, search-term highlighting, an aurora shimmer under the hero, and a living empty-state sigil.

## Included in v1.2.0

### Three separate libraries

- **Official Archive:** 237 indexed Monster Girl Encyclopedia profiles, each marked as Official and linked to its canonical reference page.
- **AI Forged:** 259 bundled original/public-domain archetypes plus anything created through OpenRouter.
- **User Creations:** hand-written records, imports, edits, and personal worldbuilding.

The sidebar, filters, card badges, counts, editor, and backup format all preserve the library type. A generated entry cannot silently masquerade as official material.

### Illustrated libraries

The three libraries use different image sources:

- **Official Archive:** images are downloaded from the canonical wiki by `cache_official_images_windows.bat`.
- **AI Forged:** entries such as **Aello** and **Ahuizotl Maiden** are original generated records. They have no canonical wiki image and therefore cannot be filled by the Official cache. Use **Settings → Image AI → Generate Missing Portraits** or `generate_missing_ai_images_windows.bat`.
- **User Creations:** attach local art or include them in the same generated-art batch.

The app now starts in the Official Archive by default. The combined All Entries view is grouped into Official, AI, and User sections rather than interleaving them. Blank AI/User cards contain a direct **Generate portrait** action.

Batch generation is resumable because every finished image is attached immediately. It supports ComfyUI, OpenAI API, and Gemini API. Hosted API batches require an explicit billing confirmation and default to a conservative ten-image limit. Manual ChatGPT/Gemini subscription handoff remains available per entry but cannot be automated in a batch.

### Images

Official artwork caching uses a **real installed Chromium browser**, not HTTP impersonation. The source wiki currently places its pages, MediaWiki API, and image redirects behind a Cloudflare challenge that returns HTTP 403 to ordinary app requests.

Use either:

- **Settings → Data → Open Real-Browser Cache**
- Double-click `cache_official_images_windows.bat`

The helper:

1. Prefers Microsoft Edge, then Chrome, Brave, and Opera. `MONSTRUM_BROWSER` can override the executable.
2. Launches one Playwright-owned persistent browser context and stores the solved session in `userdata/official-browser-profile-v2/`.
3. Lets you complete any visible Cloudflare check. Keep the dedicated browser window open while caching.
4. Indexes both the live **Mugshot Image** category and the larger **Profile Image** category.
5. Caches three distinct media classes for every Official entry:
   - **Mugshot:** the square image used on archive cards.
   - **Standalone portraits:** every numbered file matched to the entry, such as `Apsara_0.jpg`, `Apsara_1.jpg`, and so on.
   - **Entry images:** every matched English/Japanese encyclopedia page, such as `Apsara eng1.png` or `Apsara jp1.png`.
6. Uses exact normalized base-name matching so `Abaddon` cannot steal `Abaddon Folk` media.
7. Stores a structured `extra.official_media` manifest with each asset's filename, file-page URL, resolved URL, local path, type, index, and language.
8. Reuses healthy local files on later runs and retries only incomplete bundles or failed assets. `--refresh` redownloads everything.
9. Stores all binaries under `userdata/media/`.

The UI keeps the media roles separate but no longer leaves a blank Official card when one media class is missing. Cards prefer the mugshot, then fall back to a standalone portrait and finally the first entry image. Detail heroes prefer full portraits, then mugshots, then entry images. The detail panel still exposes dedicated **Mugshot**, **Portraits**, and **Entry Images** galleries with a full-size viewer.

The release ZIP does not redistribute the franchise image binaries. It stores the reference index, source URLs, and user-side browser cache tooling.

### AI and integrations

- Fast search across names, aliases, tags, summaries, and all three libraries
- Family, habitat, rarity, danger, favorites, and recency views
- Full codex editor with anatomy, ecology, culture, abilities, weaknesses, image prompts, provenance, and roleplay fields
- **OpenRouter lore forge** with structured JSON output and provider fallback
- **OpenAI Images API** support
- **Google Gemini image API** support
- **ComfyUI local server bridge** using API-format workflows and placeholders
- **ChatGPT/Gemini subscription handoff** for copying prompts and manually attaching results
- Local image attachment and generated-image archive
- JSON and CSV import
- Full codex backup
- **SillyTavern exports:** CCv3 JSON, metadata-embedded CCv3 PNG, CHARX, and lorebook JSON
- Desktop shell on Windows through Edge WebView2, with browser fallback


## v1.2.0 generated-art separation

- Corrects the source misunderstanding exposed by blank cards: Aello, Ahuizotl Maiden, and the purple-badged Akaname are **AI Forged**, not Official records. The Official cache deliberately cannot assign franchise artwork to them.
- Adds one-click missing-art actions to AI and User cards.
- Adds resumable batch portrait generation through ComfyUI, OpenAI API, or Gemini API.
- Adds a Windows batch launcher and progress/failure reports under `userdata/`.
- Requires explicit confirmation before hosted API batches that may create charges.
- Starts in the Official Archive by default and groups the combined view by library.
- Adds API endpoints and live UI status for background image batches.
- Automated coverage is now twenty-seven tests.

Run `generate_missing_ai_images_windows.bat --limit 10` or use Settings → Image AI. Existing images are skipped unless `--refresh` is deliberately supplied.

## v1.1.7 missing-portrait repair

- Fixes Official cards such as Aka-Oni and Alraune remaining blank when their mugshot filename did not match the catalog title.
- Adds a local display fallback chain: mugshot → standalone portrait → entry image.
- Adds a canonical-entry-page fallback that resolves the species page's own lead image instead of using looser cross-species fuzzy matching.
- Expands Profile Image matching to compact names such as `AkaOni0.jpg` and exact unnumbered portraits such as `Alraune.jpg`.
- Uses each entry's `/Extra` page as a secondary source of strictly classified portrait and entry-page links when the global category index misses them.
- Preserves healthy previously cached media when a category page is incomplete during a later sync.
- Bumps the Official media manifest to schema v3, causing a one-time repair pass while reusing files already present on disk.
- Adds correct card/detail styling when the fallback asset is a full portrait or an entry page.
- Automated coverage is now twenty-four tests.

Run `cache_official_images_windows.bat` normally after installing. Existing cached files are reused; `--refresh` is not required.


## v1.1.6 official media archive

- Expands each Official record from one image into a complete media bundle.
- Caches the dedicated mugshot, every numbered standalone portrait, and every English/Japanese entry page found in the source categories.
- Adds a schema-v2 media manifest under `extra.official_media`.
- Keeps mugshots as card art while using the first full portrait for the detail hero when available.
- Adds separate inline galleries and a full-size viewer with source-file links.
- Migrates v1.1.5 mugshot metadata automatically and performs a one-time Profile Image indexing pass.
- Validates local paths on every incremental run and retries partial failures.
- Cache status now reports complete entries, mugshots, standalone portraits, entry pages, and total assets.
- Automated coverage is now twenty-one tests.

## v1.1.5 portrait correction

- Reverses the old asset priority: **mugshots are now the only official card/detail portrait source**.
- Stops using `eng1` encyclopedia-page scans as card backgrounds.
- Automatically detects v1.1.0-v1.1.4 cached profile sheets and schedules them for replacement, even without `--refresh`.
- Preserves an old page scan path in entry metadata as `official_profile_sheet_path` while switching `image_path` to the mugshot.
- Uses exact normalized filename matching and one-to-one record consumption so a broad name cannot steal a related species' portrait.
- Hides known page scans in the UI immediately, before the repair cache finishes.
- Uses `object-fit: contain` and portrait-safe spacing for square official mugshots instead of tall-image cropping.
- Counts only verified mugshot/user-attached/generated portraits in the cache progress display.
- Automated coverage is now eighteen tests.

Run `cache_official_images_windows.bat` normally after installing this version. **Do not add `--refresh`; old profile sheets are detected and repaired automatically.**

## v1.1.4 browser ownership hotfix

- Removes the external browser process plus Chrome DevTools Protocol attachment path that could leave Playwright holding a dead `about:blank` page.
- Launches one Playwright-owned persistent browser context directly.
- Prefers Edge and Chrome over Opera GX because Opera may replace its startup page during automation attachment.
- Uses a new `userdata/official-browser-profile-v2/` directory, avoiding stale locks and restored tabs from v1.1.2-v1.1.3.
- Reacquires a live page whenever Chromium replaces or closes the startup page.
- Retries a failed navigation once after discarding the dead page.
- Uses the same recovery path for category pages, file pages, and image downloads.
- Keeps one controlled tab after the category page is established.
- Keeps detailed progress in `userdata/official-browser-cache.log` and the final report in `userdata/official-image-cache-report.txt`.
- Automated coverage is now fifteen tests, including a simulated `TargetClosedError` recovery.

## Start on Windows

Double-click:

```text
run_windows.bat
```

The first launch creates `.venv`, installs the Python dependency set, starts the local server, and opens the desktop window. Data is stored in `userdata/`.

For a browser-only launch, use `run_browser_windows.bat`.

## Upgrade from v1.0 or v1.1

Extract v1.2.0 over a copy of your existing installation, or copy the old `userdata/` folder into the new directory. On first launch the database migration:

1. Adds the `catalog_kind` and `image_url` fields.
2. Places the bundled foundation into **AI Forged**.
3. Keeps hand-created records in **User Creations** where identifiable.
4. Adds any missing Official Archive records without overwriting your edits.

Back up `userdata/` before replacing files.

## Cache all official media

From the UI, open **Settings → Data** and select **Open Real-Browser Cache**, or run:

```text
cache_official_images_windows.bat
```

A visible browser window opens. Complete any Cloudflare check in that window. The terminal and app status text continue automatically once the wiki accepts the session. Verified mugshots are reused. The Profile Image category is scanned for all numbered portraits and all English/Japanese entry pages. Healthy assets are skipped and partial failures are retried.

To redownload every official media asset:

```text
.venv\Scripts\python.exe -m tools.cache_official_images --transport browser --refresh
```

To force a particular browser executable:

```text
set MONSTRUM_BROWSER=C:\Path\To\browser.exe
cache_official_images_windows.bat
```

Diagnostics:

```text
userdata/official-browser-cache.log
userdata/official-image-cache-report.txt
```

The legacy direct HTTP mode remains available only for diagnostics:

```text
.venv\Scripts\python.exe -m tools.cache_official_images --transport http
```

## Build a portable Windows app

Run:

```text
build_windows_exe.bat
```

The build appears at:

```text
dist\Monstrum Codex Infinite\Monstrum Codex Infinite.exe
```

This is an on-Windows build step because PyInstaller does not correctly cross-compile Windows binaries from Linux.

## Generate missing AI/User portraits

From the app, open **Settings → Image AI**, configure a provider, and choose **Generate Missing Portraits**. The default maximum is ten images per run.

From Windows:

```text
generate_missing_ai_images_windows.bat --limit 10
```

Examples:

```text
generate_missing_ai_images_windows.bat --provider comfyui --limit 0
generate_missing_ai_images_windows.bat --provider openai --limit 10
generate_missing_ai_images_windows.bat --provider gemini --kinds ai,user --limit 25
```

`--limit 0` means all missing entries. OpenAI and Gemini batches ask for explicit confirmation because API usage may be billable. Diagnostics are written to:

```text
userdata/ai-image-generation.log
userdata/ai-image-generation-report.txt
```

## AI setup

Open **Settings → Lore AI**:

1. Enter an OpenRouter API key.
2. Fetch models.
3. Choose a default model.

Open **Settings → Image AI** for OpenAI or Google API keys.

### Subscription caveat

A ChatGPT Plus/Pro subscription and a Google Gemini consumer subscription are not API credentials. The image studio therefore includes manual handoff buttons that copy the prompt and open the relevant consumer application. Attach the finished image afterward.

## ComfyUI setup

1. Start ComfyUI, normally at `http://127.0.0.1:8188`.
2. Enable Dev Mode.
3. Build and test a portrait workflow.
4. Use **Save (API Format)**.
5. Paste the JSON into **Settings → ComfyUI**.
6. Replace workflow values with any of these exact placeholders:

```text
{{PROMPT}}
{{NEGATIVE_PROMPT}}
{{WIDTH}}
{{HEIGHT}}
{{SEED}}
```

A template is provided in `workflows/comfyui_api_template.json`.

## SillyTavern

Open any codex entry and choose **Export**:

- **CCv3 JSON:** editable Character Card V3 data
- **CCv3 PNG:** avatar image with embedded `chara` and `ccv3` metadata
- **CHARX:** card archive with JSON and icon
- **Lorebook JSON:** species-focused World Info payload

Remote official preview art is embedded only after it has been cached locally.

## Import formats

### JSON

```json
[
  {
    "name": "Example",
    "catalog_kind": "user",
    "family": "Fae",
    "summary": "..."
  }
]
```

Valid `catalog_kind` values are `official`, `ai`, and `user`.

### CSV

Array fields use `|` separators:

```csv
name,catalog_kind,family,abilities,tags
Example,user,Fae,Illusion|Moonlight,fae|forest
```

## Local files

```text
userdata/codex.sqlite3  Codex and saved settings
userdata/media/         Generated, attached, and cached portraits
```

API keys are saved locally in SQLite when settings are saved. Do not share your `userdata` folder.

## Developer launch

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux: source .venv/bin/activate
pip install -r requirements.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 17373
```

Then open `http://127.0.0.1:17373`.

# Changelog

## 1.6.2 — Command and path injection hardening

- Batch image generation now maps provider/kind arguments through a constant allowlist and launches `python -m tools.generate_ai_images` as an argv list with `shell=False`.
- `/media/{filename}` resolves and bound-checks the path inside `userdata/media`, rejecting `..`, absolute paths, and NUL.

## 1.6.1 — Real Text For The Official Archive

- New real-browser text harvester (`app/wiki_text_cache.py` + `tools/cache_official_text.py`,
  rerun anytime via `cache_official_text_windows.bat`): walks every official entry's canonical
  source page through the same Cloudflare-passing persistent browser that cached the artwork,
  waits out the challenge, extracts the article prose (up to ~4000 chars) and stores it in
  each entry's `lore`.
- Officials with cached lore now show the **actual article text** as Field Lore; the stub
  apology and cache button hide themselves once real text exists.
- `tests/test_official_lore.py`: guards against challenge-page leakage and empty caches.

## 1.6.0 — The Other Page

- Clicking a specimen **stays in the codex view**: the side panel opens over the grid exactly as before.
- New **"Show more info"** button (under the section quick-nav) opens a full-screen dossier page for that specimen — the "other page".
- The other page carries an exclusive **Living Environment** stage: a large animated habitat scene (danger-reactive) plus Beloved/Avoided terrain lines from the Naturalist Profile.
- The action bar physically moves onto the page and back, so favorite/edit/export/nav keep working everywhere; ←/→ browse entries while immersed; Esc returns to the codex view.
- Dex layer retained on both surfaces: № registry badge, sticky quick-nav tabs with scrollspy, numbered sections, aliases.

## 1.5.0 — The True Codex

- Added a **Naturalist Profile** to every entry's detail panel: diet, behavior (activity cycle, social structure, disposition, and danger-scaled response to trespass), likes, dislikes, beloved terrain, and avoided terrain.
- Profiles are derived deterministically from each entry's own fields (slug-seeded), so they are stable across restarts, unique per species, and stored nowhere — no schema changes.
- Family archetypes drive the flavor (aquatic, forest, sky, cosmic, infernal, undead, swarm, beast, fae, construct); habitat keywords drive the hated-environment line.
- `desktop.py` now detects an already-running instance and reuses it instead of crashing with a port-bind error on double launch.
- Bumped cache-busted frontend assets and the backend version to v1.5.0.

## 1.4.0 — Living Codex II: Foil & Fire

- Added **danger-reactive habitat scenes**: particle density, pulse rate, brightness, and saturation now scale with an entry's danger rating (three heat tiers), so a Danger 5 volcanic lair visibly burns harder than a Danger 1 meadow.
- Added an **animated holographic foil ring** on Rare, Mythic, and Legendary cards — a rotating conic-gradient border (gold → pink → cyan → violet) rendered with a masked `::after`, GPU-composited via a registered `@property` angle animation.
- Added **card tilt**: hovering a grid card gives it a subtle perspective lean that follows the cursor (single delegated rAF-throttled pointer listener; disabled in compact mode and on coarse pointers).
- Added **detail-hero parallax**: the portrait, living scene canvas, and both mist layers drift at different depths under the pointer.
- Added a **Recently Viewed strip** under the page hero — thumbnail chips for the last eight opened specimens, persisted in localStorage, with click-to-reopen and automatic pruning of deleted entries.
- Added a **keyboard cheatsheet** (`?` key or the new `?` topbar button): Ctrl-K search focus, S surprise, F favorite, ←/→ navigation, Esc close.
- Added **favorite heart-bursts** — pink heart/spark particles pop from both the card favorite button and the detail-panel button when favoriting.
- Reduced-motion users get all of it frozen or disabled; foil, bursts, tilt transforms, and parallax are inert under `prefers-reduced-motion`.
- Bumped cache-busted frontend assets and the backend version to v1.4.0.

## 1.3.0 — The Living Codex

- Added procedurally animated **living habitat scenes**: every entry's living space now breathes on its cards and in the detail hero (ember glow for volcanic and sulfur lairs, snowfall for mountains and highlands, rising bubbles for seas and rivers, fireflies for forests, drifting dust for deserts, twinkling crystals for caverns, falling stars for cosmic habitats, wisps for spectral places, and more).
- Scenes are generated locally on a lightweight canvas engine — no GIFs, no network, infinite loop, and they pause offscreen, on hidden tabs, and under `prefers-reduced-motion`.
- Cards show a subtle animated atmosphere layer over the artwork plus a habitat scene glyph; the detail hero adds drifting habitat-colored mist layers and a slow breathing vignette.
- Added **Surprise Me** (topbar dice, `S` key) to open a random specimen from the current view.
- Added **previous/next navigation** through the current filtered view with arrow-key support (`←`/`→`) and `F` to toggle favorite while the panel is open.
- Added staggered card entrance animation, hero specimen-counter count-up, an aurora shimmer line under the hero, a living empty-state sigil, and search-term highlighting in card names and summaries.
- Added a `surprise-glyph` spin, reduced-motion fallbacks, and disabled-state styling for the new navigation arrows.
- Bumped cache-busted frontend assets and the backend version to v1.3.0.

## 1.2.0

- Clarified that blank purple-badged entries such as Aello are AI-Forged originals, not missing Official cache records.
- Added a direct Generate portrait/Add portrait action to every AI/User card without local art.
- Added resumable background batch generation for AI and User libraries through ComfyUI, OpenAI API, and Gemini API.
- Added hosted-provider billing confirmation, batch limits, live status, failure logging, and a standalone Windows launcher.
- Added `app.ai_media` prompt construction, provider validation, local-image detection, and per-entry generation history.
- Changed the default startup library to Official Archive.
- Grouped All Entries into separate Official, AI-Forged, and User sections.
- Added frontend and API cache-busting for v1.2.0.
- Increased automated coverage to twenty-seven tests.

## 1.1.7

- Fixed Official cards remaining blank when the dedicated mugshot could not be matched or loaded.
- Added card fallback order: mugshot, standalone portrait, then entry-page image.
- Added detail fallback order: standalone portraits, mugshot, then entry-page images.
- Added canonical entry-page lead-image recovery for mugshots whose source filenames differ from the catalog title.
- Added per-entry `/Extra` page recovery for profile media missed by the global category index.
- Added compact numbered portrait matching such as `AkaOni0.jpg` and exact unnumbered portrait matching such as `Alraune.jpg`.
- Preserved valid old portrait and entry-page files when a later category crawl is incomplete.
- Bumped `extra.official_media` to schema v3 so old installs receive one automatic repair pass without redownloading healthy files.
- Added media-kind-aware frontend fallback queues and styling.
- Increased automated coverage to twenty-four tests.

## 1.1.6

- Expanded Official media from one mugshot into a three-part archive: mugshot, standalone portraits, and encyclopedia entry pages.
- Added Profile Image category indexing alongside the 237-file Mugshot Image category.
- Added exact classification for numbered portrait files such as `Apsara_0.jpg` and localized entry pages such as `Apsara eng1.png` or `Apsara jp1.png`.
- Added `extra.official_media` schema v2 with per-asset source filename, file page, resolved URL, local path, index, and language metadata.
- Cards continue using mugshots, while official detail heroes now prefer the first full-size portrait.
- Added separate Mugshot, Portraits, and Entry Images galleries with a full-size media viewer and canonical source-file links.
- Added incremental multi-asset caching, missing-file validation, partial-failure retry, and richer cache/report counters.
- Automatically migrates v1.1.5 mugshot metadata into the new media manifest and schedules every Official entry for one-time Profile Image indexing.
- Updated Windows cache launcher, in-app status text, documentation, and cache-busted frontend assets.
- Increased automated coverage to twenty-one tests.

## 1.1.5

- Fixed official cards using tall English encyclopedia-page scans instead of the dedicated square mugshot portraits.
- Changed the live cache index to the 237-file Mugshot Image category only.
- Added exact normalized alias matching, ambiguity rejection, and one-to-one portrait assignment.
- Added deterministic mugshot-only redirect fallbacks with PNG, JPG, JPEG, and WebP variants.
- Automatically treats v1.1.0-v1.1.4 profile-sheet caches as pending repairs without requiring `--refresh`.
- Preserves old profile-sheet paths in metadata while replacing the active `image_path` with the mugshot.
- Hides known profile sheets from portrait slots before recaching.
- Made remote official art fallback opt-in rather than implicitly enabled when the setting is absent.
- Added portrait-safe card/detail styling using contained square artwork.
- Updated cache counts, terminal output, report wording, UI status, and asset cache-busting.
- Increased automated coverage to eighteen tests.

## 1.1.4

- Replaced external browser launch plus CDP attachment with a Playwright-owned persistent browser context.
- Fixed `TargetClosedError` when Opera/Chromium replaced or closed the selected `about:blank` startup page.
- Added live-page reacquisition and one automatic navigation retry.
- Applied recovery to category navigation, file-page resolution, and image downloads.
- Prefer Edge, Chrome, and Brave before Opera for automation stability; `MONSTRUM_BROWSER` still overrides selection.
- Moved the cache session to `userdata/official-browser-profile-v2` to avoid stale profile locks and restored tabs.
- Updated the cache BAT and terminal guidance for the new profile and browser lifecycle.
- Increased automated coverage to fifteen tests.

## 1.1.3

- Fixed the real-browser helper opening duplicate wiki tabs plus a blank Playwright tab.
- Removed the separate download page; category indexing, file resolution, and downloads now share one controlled tab.
- Clears only session-restore tab files from the dedicated browser profile while retaining cookies and site data.
- Forces navigation to the Profile Image category instead of accepting the wiki homepage as a successful cache page.
- Recognizes equivalent MediaWiki pretty-path and query-string category URLs.
- Re-navigates to the requested category after verification if Cloudflare leaves the browser on the homepage.
- Switched category entry points to canonical MediaWiki query URLs.
- Increased automated coverage to thirteen tests.

## 1.1.2

- Replaced fake-browser HTTP image fetching with a real installed Chromium browser connected over CDP.
- Added Opera GX, Opera, Edge, Chrome, Brave, and override-path detection.
- Added a persistent dedicated browser profile for Cloudflare cookies and site checks.
- Added live Profile Image and Mugshot category indexing with profile-first filename matching.
- Added deterministic browser-navigation fallbacks when a category record is absent.
- Reworked the in-app cache button to launch and monitor the browser helper instead of issuing 237 HTTP requests.
- Added browser-cache status and launch API routes.
- Disabled unreliable remote filename hotlink guessing by default.
- Added browser process, cache progress, and final failure logs.
- Increased automated coverage to eleven tests.

## 1.1.1

- Fixed the standalone image cache launcher failing to import `app`.
- Added module-safe and direct-script-safe cache execution.
- Added direct browser mugshot/profile fallbacks for official cards and detail views.
- Added Chromium-compatible HTTP fallback for MediaWiki/API/image caching.
- Added stale-image retry behavior and per-run cache diagnostics.
- Added frontend asset cache-busting.

## 1.1.0

- Split the codex into Official, AI Forged, and User libraries
- Added 237 source-linked Official Archive profile records
- Added distinct navigation, counts, filters, badges, titles, and provenance fields
- Added automatic official preview-art resolution for visible cards and detail pages
- Added one-click local caching for individual or all official previews
- Added `cache_official_images_windows.bat` and a Python cache utility
- Added `image_url` and `catalog_kind` database migration fields
- Added upgrade-safe official seeding without overwriting existing records
- Updated editor and import format to preserve library type and source URLs
- Increased smoke coverage to seven tests, including exact catalog separation counts

## 1.0.0

- Initial finalized local-first release
- 259-entry foundational codex
- Grabber-inspired browsing shell
- OpenRouter structured lore forge
- OpenAI, Gemini, ComfyUI, and manual subscription image paths
- SillyTavern CCv3 JSON, PNG, CHARX, and lorebook exports
- JSON/CSV import and full backup
- Windows desktop launcher and portable-build script

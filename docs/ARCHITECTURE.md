# Architecture

## Runtime

- FastAPI local server
- SQLite database with WAL enabled
- Static dependency-free frontend
- Optional pywebview desktop shell

## Provider boundaries

- OpenRouter: `POST /api/v1/chat/completions`, JSON Schema first, JSON object fallback
- OpenAI: `POST /v1/images/generations`
- Gemini: `models/{model}:generateContent` with image response modality
- ComfyUI: `POST /prompt`, poll `/history/{prompt_id}`, retrieve `/view`

All hosted keys and calls remain on the local backend rather than being exposed inside frontend source code. Saved keys are still stored locally in SQLite and should be treated as secrets.

## Data model

Each entry stores taxonomy, rarity, danger, origin, habitat, prose sections, list fields, image metadata, source/provenance, rating, roleplay fields, and extensible JSON.

## Extensibility

New providers can be added in `app/providers.py`, routes in `app/main.py`, and UI options in `web/assets/app.js`. The codex importer accepts partial records and fills sensible defaults.

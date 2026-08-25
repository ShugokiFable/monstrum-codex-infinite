# Official Archive design

The Official Archive is intentionally distinct from AI and user material.

## Record rules

- `catalog_kind`: `official`
- `source_kind`: `official`
- `source_name`: `Monster Girl Encyclopedia`
- `source_url`: canonical reference-page URL
- `extra.official_page_title`: page title used by the media matcher

Official slugs are prefixed with `official-` so a canonical record can coexist with an AI or user interpretation bearing the same species name.

## Multi-asset media flow

1. The browser cache indexes both **Mugshot Image** and **Profile Image** categories.
2. Every entry stores a structured `extra.official_media` manifest with:
   - one `mugshot`
   - all standalone numbered `portraits`, such as `Apsara_0.jpg`
   - all English and Japanese `entry_images`, such as `Apsara eng1.png`
3. Cards prefer the dedicated mugshot, then fall back to a standalone portrait and finally an entry-page image so cached Official entries do not render as blank cards.
4. The detail hero prefers the first full-size portrait, then the mugshot, then an entry-page image.
5. The detail panel shows separate Mugshot, Portraits, and Entry Images galleries. Entry scans never masquerade as portrait art.
6. Exact normalized base-name matching prevents broad names from claiming related species files.
7. Missing mugshot category records fall back to exact `Special:Redirect/file/<stem>Mug.<ext>` candidates and then to the lead image on that entry's canonical species page.
8. Each locally cached asset retains its source filename, file-page URL, resolved image URL, local path, type, index, and language where applicable.
9. The cache can inspect an entry's `/Extra` page for strictly matched profile files that were absent from the global category crawl. Incremental runs preserve and reuse healthy files while retrying incomplete or failed media bundles. `--refresh` redownloads everything.
10. The canonical source URL remains visible in the detail panel.

The packaged release does not contain the franchise image files. The user-side browser cache stores them under `userdata/media/`.

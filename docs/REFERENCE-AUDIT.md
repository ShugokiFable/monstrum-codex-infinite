# Grabber reference audit

The uploaded reference is a packaged build of Bionus Grabber using Qt 6. The inspected build contains site adapters, theme packs, local caches, favorites, history files, tag databases, source configuration, and a dock-oriented browsing layout.

Patterns retained conceptually:

- Immediate search as the center of the application
- Dense card browsing rather than document-by-document navigation
- Local cache and favorites
- Multiple source/provider adapters behind one interface
- Filters and source metadata visible beside the content
- Exportable, portable local data

Patterns intentionally changed:

- Booru posts become structured codex entries
- Site adapters become lore/image provider bridges and importers
- Download queues become generation jobs
- Tag search becomes taxonomy search
- Grabber's Qt implementation and source code are not included or copied

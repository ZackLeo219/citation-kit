# Changelog

All notable changes to citation-kit are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) loosely; we don't
yet promise strict semver across minor versions until v1.0.

## [0.2.0] — 2026-05-07

Multi-turn support, two new storage backends, optimistic locking, and
reference integrations. Targets open-source readiness — the v0.1
single-turn core was solid but missed three things that block real-world
adoption: multi-turn conversation flow, more storage backends, and
concurrent-write correctness.

### Added

- **`rewrite_history_with_placeholders()`** + `rewrite_text_with_placeholders()`
  — multi-turn helper. Reverse-maps `[N]` markers in past assistant messages
  back to `{{cite:cite_id}}` placeholders using the registry's per-turn
  allocation snapshots. Without this, multi-turn conversations break: the
  LLM sees rendered `[N]` in history and copies that pattern instead of
  writing fresh placeholders, leaving orphan refs and an empty references
  section. (Validated as the exact failure mode that broke bridge_agent's
  Q5–Q9 in our integration test.)

- **`SQLiteStore`** — stdlib-only, no extras. Single-file persistence + SQL.
  Persistent connection for `:memory:` (each fresh sqlite3 connect to
  `:memory:` is a separate ephemeral DB), short-lived connections per-op
  for file-backed paths.

- **`RedisStore`** — `[redis]` extra. Pipelined writes, optional TTL for
  inactive-conversation auto-cleanup. WATCH/MULTI/EXEC for compare-and-swap.

- **Optimistic locking** on SQLite/Postgres/Redis: `aload_with_version()` +
  `asave_with_version(expected_version)`. Use when multiple workers may
  write the same `scope_id` concurrently. The plain `asave()` stays
  unconditional / last-write-wins.

- **`citation_kit/integrations/`** — three copy-paste-customize references:
  - `conversation_jsonb.py` — embed registry into an existing
    `conversations.metadata` JSONB column (the bridge_agent pattern)
  - `langgraph.py` — pass registry through LangGraph state channels
  - `sqlalchemy.py` — wrap a SQLAlchemy 2.0 async session

- **`citation_kit.observability`** — `logger` (standard
  `logging.getLogger("citation_kit")`) + `set_metric_hook(fn)` for wiring
  Prometheus / StatsD / OpenTelemetry from outside. Five built-in counters
  (`register`, `dedup_hit`, `placeholder_seen`, `placeholder_orphan`,
  `references_emitted`).

- **`renderer.feed()` / `renderer.flush()` / `renderer.references_section()`**
  — incremental API for SSE/queue loops that own their own iteration.
  Composes cleanly with token-stream emit loops without wrapping into
  `render_stream()`.

- **`BACKENDS.md`** — full decision tree for picking a backend, comparison
  table, optimistic-locking guide, multi-tenancy notes, schema migration.

### Changed

- **PostgresStore** schema gained a `version` column for compare-and-swap.
  Backwards-compatible: `ADD COLUMN IF NOT EXISTS` runs on every
  `_ensure_table()`, so v0.1 deployments upgrade transparently on first
  v0.2 write.

- **Postgres extras**: new `[redis]` extra; `[all]` extra installs both
  `[postgres]` and `[redis]` for one-line prod install.

- **README** — added "Multi-turn" section explaining the conversation
  history trap + the `rewrite_history_with_placeholders` fix. Backend
  comparison table now has 5 entries (was 3).

### Numbers

- Tests: **89 → 114** (+25 new for history rewriter, SQLite, version-locking)
- Backends in the box: **3 → 5** (memory, json, sqlite, postgres, redis)
- Reference integrations: 0 → 3 (langgraph, sqlalchemy, conversation_jsonb)
- Public exports: 23 → 30

### Migration from v0.1

Almost zero breaking changes for existing single-turn users. The new
`feed()`/`flush()` API is additive; `render()` and `render_stream()` work
exactly as before.

For multi-turn use, the migration is two steps:
1. Pick a `RegistryStore` backend (SQLiteStore is the simplest — no extras).
2. Wrap your existing `run()` with: `aload` at start → mutate registry as
   normal → `asave` at end. Add a `rewrite_history_with_placeholders()`
   call before sending history to the LLM.

Postgres users with v0.1 deployments: nothing to do. The `version` column
is auto-added on first save.

---

## [0.1.0] — 2026-05-06

Initial public release.

### Added

- **Placeholder protocol** — opaque `{{cite:<id>}}` markers the LLM writes
  verbatim; server expands to numeric `[N]` or chip-style markdown links
  via `CitationRenderer`. Decouples synthesis (LLM) from bookkeeping
  (server).

- **`CitationRegistry`** — per-thread record pool with idempotent merge,
  cross-source dedup (DOI > PMID > arXiv > S2 > URL hash). Scan
  placeholders, allocate `[N]` indices, serialize for persistence.

- **`CitationRenderer`** — `numeric` mode (`[N]` + auto-generated
  `## 参考文献`) or `chip` mode (markdown link with title attribute).
  Streaming buffer handles placeholders split across chunk boundaries.

- **`validate()` + `autofix_leaks()`** — deterministic post-render check
  for leaked placeholders, orphan numeric refs, unused records.

- **Stores**: `InMemoryStore` (default, volatile), `JSONFileStore`
  (single-machine durability), `PostgresStore` (extras: `[postgres]`).

- **10 retrieval-API adapters**: Tavily, Exa, Brave, Serper (web search);
  PubMed, Semantic Scholar, arXiv, Crossref, OpenAlex, Europe PMC
  (academic literature). Each is a single `parse(raw_response) ->
  ParseResult` function; cross-source dedup via canonical `cite_id`.

- **89 tests** via stdlib unittest.

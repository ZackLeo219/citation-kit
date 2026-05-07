# Choosing a storage backend

`citation-kit` ships with **5 backends** out of the box. Pick by deployment
shape — most projects only need one. All backends implement the same
3-method async `RegistryStore` protocol so swapping later is trivial.

## TL;DR decision tree

```
┌─ Single process, no persistence needed (testing / one-shot scripts)
│      → InMemoryStore                                       (default, no setup)
│
├─ Single machine, persistence across restarts
│      ├─ Just one user / dev environment
│      │      → JSONFileStore                                (no extras, one file/scope)
│      │
│      └─ Need SQL-style queries or want a single .db file
│             → SQLiteStore                                  (stdlib, no extras)
│
└─ Multiple processes / machines (production)
       ├─ Already have Postgres in your stack
       │      → PostgresStore                                (extras: [postgres])
       │
       ├─ Already have Redis (or want sub-ms latency)
       │      → RedisStore                                   (extras: [redis])
       │
       └─ Already have a "conversations" / "threads" table you want to embed into
              → Custom RegistryStore implementation
                (see citation_kit/integrations/conversation_jsonb.py)
```

## Detailed comparison

| Backend | Setup | Persistence | Concurrency | Latency | Optimistic locking | Extras |
|---------|-------|-------------|-------------|---------|--------------------|--------|
| `InMemoryStore` | none | volatile (process lifetime) | single-process | ~0 | n/a | none |
| `JSONFileStore` | mkdir | filesystem | single-machine, file-locks via os.replace | low | n/a | none |
| `SQLiteStore` | one path arg | filesystem | single-machine, WAL multi-reader | low | ✅ | none |
| `PostgresStore` | DSN or pool | network DB | multi-host | ~ms | ✅ | `[postgres]` |
| `RedisStore` | URL or client | in-memory + AOF/RDB | multi-host | sub-ms | ✅ via WATCH | `[redis]` |

## Optimistic locking — when you need it

If multiple worker processes might write the **same** `scope_id` (e.g. user
runs two queries in two browser tabs against a multi-worker uvicorn), the
plain `asave` last-write-wins behavior can lose registry entries.

Three backends (`SQLiteStore` / `PostgresStore` / `RedisStore`) expose
compare-and-swap:

```python
data, version = await store.aload_with_version(scope_id)
registry = CitationRegistry.from_serializable(data)
# ... mutate registry (register new tool results, allocate indices) ...
ok = await store.asave_with_version(
    scope_id, registry.to_serializable(), expected_version=version
)
if not ok:
    # Someone else wrote first — reload, merge, retry
    ...
```

The "merge" path is straightforward because `CitationRegistry.register` is
idempotent on cite_id. Reloading the latest version, re-registering this
worker's records, and retrying converges.

## Custom backend (your own DB)

If you'd rather embed registry state into your existing schema (e.g. a JSONB
column on a `conversations` table you already have) — implement the
3-method protocol against that schema. We provide reference impls under
`citation_kit/integrations/`:

- **`conversation_jsonb.py`** — embed in `conversations.metadata` JSONB
- **`langgraph.py`** — pass through LangGraph state channels
- **`sqlalchemy.py`** — wrap SQLAlchemy 2.0 async session

Each is ~30 LOC of copy-paste-customize. Drop one of those into your project,
adjust column / table names, and pass the instance anywhere a
`RegistryStore` is expected.

## Multi-tenancy

The protocol uses opaque `scope_id` strings — there's no enforced format. If
you need namespacing (e.g. per-user thread isolation), encode it into the
scope_id:

```python
await store.aload(f"{user_id}:{thread_id}")
```

For RedisStore there's also `key_prefix`:

```python
RedisStore(url="redis://...", key_prefix=f"app:{tenant_id}:reg")
```

## Schema migration

`SQLiteStore` and `PostgresStore` both auto-create their table on first
write (idempotent `CREATE TABLE IF NOT EXISTS`). If you manage migrations
externally (Alembic, Liquibase, sqitch), pass `auto_create_table=False` and
include the schema in your migration tooling.

The current schema is two columns + `version` for optimistic locking +
`updated_at` for housekeeping. A future v0.3 may add a `meta` JSONB column
for hot-path filters; we'll keep `version` semantics stable.

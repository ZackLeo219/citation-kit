"""SQLite store. Stdlib only — no extra install needed.

One file per database; one row per scope_id. Auto-creates schema on first
save (idempotent). Uses ``aiosqlite``-free design: wraps stdlib ``sqlite3``
in ``asyncio.to_thread`` for the async API. SQLite is single-writer (with
journal-mode WAL it's better, see ``wal=True``), so don't expect this to
scale to many concurrent writers — for that, use PostgresStore or RedisStore.

Good for:
  * Embedded apps (one process, persistence across restarts)
  * Dev / single-user setups
  * Reference deployments where setup-cost-per-server matters

Schema (per-database, ``citation_registry`` table)::

    CREATE TABLE IF NOT EXISTS citation_registry (
        scope_id    TEXT PRIMARY KEY,
        data        TEXT NOT NULL,           -- json-encoded
        version     INTEGER NOT NULL DEFAULT 1,
        updated_at  INTEGER NOT NULL DEFAULT (strftime('%s','now'))
    );

Optimistic locking is implemented via the ``version`` column: ``asave_with_version``
returns False when the on-disk version doesn't match the expected one. Use
when concurrent writers are possible. The plain ``asave`` is unconditional.
"""
from __future__ import annotations

import asyncio
import json
import os
import sqlite3
from typing import Any


class SQLiteStore:
    """Stdlib-only SQLite-backed registry store.

    Args:
      db_path: filesystem path (use ``":memory:"`` for ephemeral).
      table: table name. Must be a valid Python identifier (no SQL injection
             possible via this path).
      auto_create_table: run ``CREATE TABLE IF NOT EXISTS`` on first use.
      wal: enable write-ahead log mode for better concurrency. Defaults to
           True for file-backed databases (no-op for ``:memory:``).
    """

    def __init__(
        self,
        db_path: str | os.PathLike,
        *,
        table: str = "citation_registry",
        auto_create_table: bool = True,
        wal: bool = True,
    ) -> None:
        if not table.isidentifier():
            raise ValueError(f"unsafe table name: {table!r}")
        self.db_path = str(db_path)
        self.table = table
        self.auto_create = auto_create_table
        self.wal = wal and self.db_path != ":memory:"
        self._initialized = False
        # For `:memory:`, every fresh connection is a fresh ephemeral DB —
        # so we must hold a single persistent connection. For file-backed
        # paths, we open a new short-lived connection per op (avoids
        # cross-thread contention via asyncio.to_thread).
        self._persistent_conn: sqlite3.Connection | None = None
        if self.db_path == ":memory:":
            self._persistent_conn = self._open_conn()

    def _open_conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.db_path, isolation_level=None, check_same_thread=False)
        c.row_factory = sqlite3.Row
        return c

    class _ConnCtx:
        """Context manager that yields the persistent in-memory connection
        (no close) or a fresh per-op connection (closes on exit)."""
        def __init__(self, conn, owns):
            self.conn = conn
            self.owns = owns
        def __enter__(self):
            return self.conn
        def __exit__(self, *a):
            if self.owns:
                self.conn.close()

    def _connect(self) -> "SQLiteStore._ConnCtx":
        if self._persistent_conn is not None:
            return SQLiteStore._ConnCtx(self._persistent_conn, owns=False)
        return SQLiteStore._ConnCtx(self._open_conn(), owns=True)

    def _ensure_schema_sync(self) -> None:
        if self._initialized or not self.auto_create:
            return
        with self._connect() as c:
            if self.wal:
                c.execute("PRAGMA journal_mode=WAL")
            c.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {self.table} (
                    scope_id    TEXT PRIMARY KEY,
                    data        TEXT NOT NULL,
                    version     INTEGER NOT NULL DEFAULT 1,
                    updated_at  INTEGER NOT NULL DEFAULT (strftime('%s','now'))
                )
                """
            )
        self._initialized = True

    # ───────── Async public API (RegistryStore protocol) ─────────

    async def aload(self, scope_id: str) -> dict[str, Any] | None:
        return await asyncio.to_thread(self._sync_load, scope_id)

    async def asave(self, scope_id: str, data: dict[str, Any]) -> None:
        await asyncio.to_thread(self._sync_save, scope_id, data)

    async def adelete(self, scope_id: str) -> None:
        await asyncio.to_thread(self._sync_delete, scope_id)

    # ───────── Optimistic locking ─────────

    async def aload_with_version(
        self, scope_id: str
    ) -> tuple[dict[str, Any] | None, int]:
        """Load data + current version. Use the version on the next
        ``asave_with_version`` to detect concurrent overwrites."""
        return await asyncio.to_thread(self._sync_load_with_version, scope_id)

    async def asave_with_version(
        self, scope_id: str, data: dict[str, Any], expected_version: int
    ) -> bool:
        """Compare-and-swap save. Returns True on success, False if the
        on-disk version differs from ``expected_version`` (caller should
        reload + merge + retry)."""
        return await asyncio.to_thread(
            self._sync_save_with_version, scope_id, data, expected_version
        )

    # ───────── Sync internals ─────────

    def _sync_load(self, scope_id: str) -> dict[str, Any] | None:
        self._ensure_schema_sync()
        with self._connect() as c:
            row = c.execute(
                f"SELECT data FROM {self.table} WHERE scope_id = ?", (scope_id,)
            ).fetchone()
        if row is None:
            return None
        return json.loads(row["data"])

    def _sync_load_with_version(
        self, scope_id: str
    ) -> tuple[dict[str, Any] | None, int]:
        self._ensure_schema_sync()
        with self._connect() as c:
            row = c.execute(
                f"SELECT data, version FROM {self.table} WHERE scope_id = ?",
                (scope_id,),
            ).fetchone()
        if row is None:
            return None, 0
        return json.loads(row["data"]), int(row["version"])

    def _sync_save(self, scope_id: str, data: dict[str, Any]) -> None:
        self._ensure_schema_sync()
        payload = json.dumps(data, ensure_ascii=False)
        with self._connect() as c:
            c.execute(
                f"""
                INSERT INTO {self.table} (scope_id, data, version, updated_at)
                VALUES (?, ?, 1, strftime('%s','now'))
                ON CONFLICT(scope_id) DO UPDATE SET
                    data = excluded.data,
                    version = {self.table}.version + 1,
                    updated_at = strftime('%s','now')
                """,
                (scope_id, payload),
            )

    def _sync_save_with_version(
        self, scope_id: str, data: dict[str, Any], expected_version: int
    ) -> bool:
        self._ensure_schema_sync()
        payload = json.dumps(data, ensure_ascii=False)
        with self._connect() as c:
            if expected_version == 0:
                # Insert-if-absent semantics
                cur = c.execute(
                    f"INSERT OR IGNORE INTO {self.table} (scope_id, data, version, updated_at) "
                    f"VALUES (?, ?, 1, strftime('%s','now'))",
                    (scope_id, payload),
                )
                return cur.rowcount == 1
            cur = c.execute(
                f"UPDATE {self.table} "
                f"SET data = ?, version = version + 1, updated_at = strftime('%s','now') "
                f"WHERE scope_id = ? AND version = ?",
                (payload, scope_id, expected_version),
            )
            return cur.rowcount == 1

    def _sync_delete(self, scope_id: str) -> None:
        self._ensure_schema_sync()
        with self._connect() as c:
            c.execute(f"DELETE FROM {self.table} WHERE scope_id = ?", (scope_id,))

"""Postgres store via asyncpg. JSONB column, single table, auto-migration.

Schema (created automatically on first `asave` if `auto_create_table=True`):

    CREATE TABLE <table> (
        scope_id  TEXT PRIMARY KEY,
        data      JSONB NOT NULL,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );

For deepagents this can live alongside `thread_meta` keyed by `thread_id`. For
bridge it can live alongside `conversations` keyed by `conversation_id`.

Optional dependency: `pip install asyncpg`. The class is only importable if
asyncpg is present in the environment (controlled by the parent `__init__.py`
import guard).
"""
from __future__ import annotations

import json
from typing import Any

try:
    import asyncpg  # type: ignore
except ImportError as e:  # pragma: no cover
    raise ImportError(
        "PostgresStore requires asyncpg. Install with `pip install citation-kit[postgres]` "
        "or `pip install asyncpg`."
    ) from e


class PostgresStore:
    """Async Postgres store. Pass either an asyncpg `Pool` (recommended) or a
    DSN string (we'll create our own pool lazily).

    Table is created on first save if it doesn't exist (idempotent CREATE
    IF NOT EXISTS). Disable with `auto_create_table=False` if you manage
    migrations externally.
    """

    def __init__(
        self,
        *,
        pool: "asyncpg.Pool | None" = None,
        dsn: str | None = None,
        table: str = "citation_registry",
        auto_create_table: bool = True,
    ) -> None:
        if pool is None and dsn is None:
            raise ValueError("Pass either pool=... or dsn=...")
        if not table.isidentifier():
            raise ValueError(f"unsafe table name: {table!r}")
        self._pool = pool
        self._dsn = dsn
        self._table = table
        self._auto_create = auto_create_table
        self._created = False

    async def _get_pool(self) -> "asyncpg.Pool":
        if self._pool is None:
            self._pool = await asyncpg.create_pool(self._dsn)
        assert self._pool is not None
        return self._pool

    async def _ensure_table(self) -> None:
        if self._created or not self._auto_create:
            return
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {self._table} (
                    scope_id    TEXT PRIMARY KEY,
                    data        JSONB NOT NULL,
                    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
                );
                CREATE INDEX IF NOT EXISTS {self._table}_updated_at_idx
                    ON {self._table} (updated_at);
                """
            )
        self._created = True

    async def aload(self, scope_id: str) -> dict[str, Any] | None:
        await self._ensure_table()
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                f"SELECT data FROM {self._table} WHERE scope_id = $1", scope_id
            )
        if row is None:
            return None
        d = row["data"]
        if isinstance(d, str):
            d = json.loads(d)
        return d

    async def asave(self, scope_id: str, data: dict[str, Any]) -> None:
        await self._ensure_table()
        payload = json.dumps(data, ensure_ascii=False)
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                f"""
                INSERT INTO {self._table} (scope_id, data, updated_at)
                VALUES ($1, $2::jsonb, now())
                ON CONFLICT (scope_id)
                DO UPDATE SET data = EXCLUDED.data, updated_at = now()
                """,
                scope_id, payload,
            )

    async def adelete(self, scope_id: str) -> None:
        await self._ensure_table()
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                f"DELETE FROM {self._table} WHERE scope_id = $1", scope_id
            )

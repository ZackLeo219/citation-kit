"""Persistence backends for `CitationRegistry`.

Pick one based on infra (see BACKENDS.md for the full decision guide):
  * `InMemoryStore`  — default, single process, no setup, volatile
  * `JSONFileStore`  — single-machine durability (dev / personal projects)
  * `SQLiteStore`    — single-machine durability + SQL (stdlib, zero extras)
  * `PostgresStore`  — production, distributed, ACID (extras: `[postgres]`)
  * `RedisStore`     — production, distributed, low-latency (extras: `[redis]`)

Optimistic locking
------------------
``SQLiteStore`` / ``PostgresStore`` / ``RedisStore`` expose
``aload_with_version`` + ``asave_with_version`` for compare-and-swap writes.
Use these in any environment where multiple workers may write the same
``scope_id`` concurrently (multi-worker uvicorn, autoscaled k8s, Celery
fanout). The plain ``asave`` is unconditional and last-write-wins.

Custom backends
---------------
Implement the `RegistryStore` protocol — three async methods. Reference
implementations live under ``citation_kit/integrations/`` for popular
existing storage layers (LangGraph checkpointer, SQLAlchemy session, etc.).
"""
from __future__ import annotations

from typing import Protocol, Any


class RegistryStore(Protocol):
    """Storage backend for serialized `CitationRegistry` data, keyed by some
    `scope_id` string the caller chooses (typically thread_id or
    conversation_id)."""

    async def aload(self, scope_id: str) -> dict[str, Any] | None:
        """Return the serialized registry dict for this scope, or None if not
        previously saved."""
        ...

    async def asave(self, scope_id: str, data: dict[str, Any]) -> None:
        """Overwrite the stored data for this scope. Implementations should
        be atomic / transactional where possible."""
        ...

    async def adelete(self, scope_id: str) -> None:
        """Remove all stored data for this scope. No-op if not present."""
        ...


from .memory import InMemoryStore  # noqa: E402
from .json_file import JSONFileStore  # noqa: E402
from .sqlite import SQLiteStore  # noqa: E402  (stdlib, no extras)

# Postgres / Redis are optional — only import if their SDK is installed.
try:
    from .postgres import PostgresStore  # noqa: E402, F401
except ImportError:
    PostgresStore = None  # type: ignore[assignment,misc]

try:
    from .redis import RedisStore  # noqa: E402, F401
except ImportError:
    RedisStore = None  # type: ignore[assignment,misc]


__all__ = [
    "RegistryStore",
    "InMemoryStore",
    "JSONFileStore",
    "SQLiteStore",
    "PostgresStore",
    "RedisStore",
]

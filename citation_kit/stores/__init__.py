"""Persistence backends for `CitationRegistry`.

Pick one based on infra:
  * `InMemoryStore` — default, single process, no setup
  * `JSONFileStore` — single-machine durability (dev / personal projects)
  * `PostgresStore` — production (auto-creates table, uses asyncpg)

Custom backends: implement the `RegistryStore` protocol — three async methods
(`aload` / `asave` / `adelete`).
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

# Postgres is optional — only import if asyncpg is installed.
try:
    from .postgres import PostgresStore  # noqa: E402, F401
except ImportError:
    PostgresStore = None  # type: ignore[assignment,misc]


__all__ = ["RegistryStore", "InMemoryStore", "JSONFileStore", "PostgresStore"]

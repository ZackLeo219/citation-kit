"""In-memory store. Default — no setup, no persistence beyond process lifetime."""
from __future__ import annotations

from typing import Any


class InMemoryStore:
    """Simple dict-backed store. Single process. Volatile. Ideal for tests
    and ephemeral agents."""

    def __init__(self) -> None:
        self._data: dict[str, dict[str, Any]] = {}

    async def aload(self, scope_id: str) -> dict[str, Any] | None:
        d = self._data.get(scope_id)
        return None if d is None else dict(d)  # shallow copy so caller can't mutate

    async def asave(self, scope_id: str, data: dict[str, Any]) -> None:
        self._data[scope_id] = dict(data)

    async def adelete(self, scope_id: str) -> None:
        self._data.pop(scope_id, None)

    def all_scopes(self) -> list[str]:
        """Test/debug helper — not part of the protocol."""
        return list(self._data.keys())

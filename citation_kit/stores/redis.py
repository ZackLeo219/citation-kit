"""Redis store. Optional ``redis`` extra (`pip install citation-kit[redis]`).

Best when:
  * Multiple worker processes share the same registry (distributed agent
    runtime, sticky-session not feasible)
  * Sub-millisecond latency matters more than transactional durability
  * You already have Redis in your stack and don't want a separate DB

Persistence trade-off: Redis defaults to in-memory + AOF/RDB snapshots. Tune
``save`` config or use Redis Enterprise for stronger durability if you need
hard persistence guarantees. For citation registries this is usually fine —
losing a recent registry just means the next turn's references list looks
incomplete; not a correctness regression.

Optimistic locking via Redis ``WATCH``/``MULTI``/``EXEC`` is implemented
through the ``aload_with_version`` / ``asave_with_version`` pair (uses the
underlying key's ``GET`` value as the version proxy via a parallel
``<key>:v`` integer counter).
"""
from __future__ import annotations

import json
from typing import Any

try:
    from redis import asyncio as aioredis  # type: ignore
except ImportError as e:  # pragma: no cover
    raise ImportError(
        "RedisStore requires `redis>=5`. Install with "
        "`pip install citation-kit[redis]` or `pip install redis`."
    ) from e


class RedisStore:
    """Async Redis-backed registry store.

    Args:
      client: pre-built ``redis.asyncio.Redis`` instance, OR
      url: Redis URL (``redis://...``) — we'll create our own client.
      key_prefix: namespace prefix. Final key is ``<prefix>:<scope_id>``.
                  Pick something distinctive if sharing the Redis instance
                  with other apps.
      ttl_seconds: optional expiration. Set this if you want auto-cleanup of
                   inactive conversations (e.g. 30 days). None = persist
                   forever.
    """

    def __init__(
        self,
        *,
        client: "aioredis.Redis | None" = None,
        url: str | None = None,
        key_prefix: str = "ckit:reg",
        ttl_seconds: int | None = None,
    ) -> None:
        if client is None and url is None:
            raise ValueError("Pass either client=... or url=...")
        self._client = client
        self._url = url
        self.prefix = key_prefix.rstrip(":")
        self.ttl = ttl_seconds

    async def _get_client(self) -> "aioredis.Redis":
        if self._client is None:
            self._client = aioredis.from_url(self._url, decode_responses=True)
        return self._client

    def _data_key(self, scope_id: str) -> str:
        return f"{self.prefix}:{scope_id}"

    def _version_key(self, scope_id: str) -> str:
        return f"{self.prefix}:{scope_id}:v"

    # ───────── RegistryStore protocol ─────────

    async def aload(self, scope_id: str) -> dict[str, Any] | None:
        c = await self._get_client()
        raw = await c.get(self._data_key(scope_id))
        if raw is None:
            return None
        return json.loads(raw)

    async def asave(self, scope_id: str, data: dict[str, Any]) -> None:
        c = await self._get_client()
        payload = json.dumps(data, ensure_ascii=False)
        pipe = c.pipeline()
        pipe.set(self._data_key(scope_id), payload, ex=self.ttl)
        pipe.incr(self._version_key(scope_id))
        if self.ttl:
            pipe.expire(self._version_key(scope_id), self.ttl)
        await pipe.execute()

    async def adelete(self, scope_id: str) -> None:
        c = await self._get_client()
        await c.delete(self._data_key(scope_id), self._version_key(scope_id))

    # ───────── Optimistic locking ─────────

    async def aload_with_version(
        self, scope_id: str
    ) -> tuple[dict[str, Any] | None, int]:
        c = await self._get_client()
        # Pipelined read so data + version are a tight pair (no Redis-side txn
        # needed for read-only).
        pipe = c.pipeline()
        pipe.get(self._data_key(scope_id))
        pipe.get(self._version_key(scope_id))
        raw, ver_raw = await pipe.execute()
        if raw is None:
            return None, 0
        data = json.loads(raw)
        version = int(ver_raw) if ver_raw is not None else 0
        return data, version

    async def asave_with_version(
        self, scope_id: str, data: dict[str, Any], expected_version: int
    ) -> bool:
        """WATCH/MULTI/EXEC compare-and-swap. Returns False if concurrent
        write changed the version since ``expected_version``."""
        c = await self._get_client()
        payload = json.dumps(data, ensure_ascii=False)
        data_key = self._data_key(scope_id)
        ver_key = self._version_key(scope_id)
        async with c.pipeline(transaction=True) as pipe:
            try:
                await pipe.watch(ver_key)
                current = await pipe.get(ver_key)
                current_v = int(current) if current is not None else 0
                if current_v != expected_version:
                    await pipe.unwatch()
                    return False
                pipe.multi()
                pipe.set(data_key, payload, ex=self.ttl)
                pipe.incr(ver_key)
                if self.ttl:
                    pipe.expire(ver_key, self.ttl)
                await pipe.execute()
                return True
            except aioredis.WatchError:
                return False

"""JSON-file store. One file per scope_id under a configured directory.

Atomic writes via tempfile + os.replace. Filenames are URL-safe encoded so
arbitrary scope_ids (UUIDs, paths, etc.) work without collisions.
"""
from __future__ import annotations

import asyncio
import json
import os
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import quote


class JSONFileStore:
    """Each `scope_id` → one JSON file under `root_dir`.

    Writes are atomic: temp file in same dir + os.replace. Concurrent writes
    to the same scope race; if you need cross-process coordination, layer a
    file lock or move to PostgresStore.
    """

    def __init__(self, root_dir: str | os.PathLike) -> None:
        self.root = Path(root_dir)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, scope_id: str) -> Path:
        # quote with empty `safe=''` so `/` becomes `%2F` — no accidental
        # subdirectories from scope_ids that look like paths.
        return self.root / (quote(scope_id, safe="") + ".json")

    async def aload(self, scope_id: str) -> dict[str, Any] | None:
        return await asyncio.to_thread(self._sync_load, scope_id)

    async def asave(self, scope_id: str, data: dict[str, Any]) -> None:
        await asyncio.to_thread(self._sync_save, scope_id, data)

    async def adelete(self, scope_id: str) -> None:
        await asyncio.to_thread(self._sync_delete, scope_id)

    def _sync_load(self, scope_id: str) -> dict[str, Any] | None:
        p = self._path(scope_id)
        if not p.exists():
            return None
        try:
            with p.open("r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return None

    def _sync_save(self, scope_id: str, data: dict[str, Any]) -> None:
        p = self._path(scope_id)
        # atomic via temp file in same dir
        fd, tmp_path = tempfile.mkstemp(
            prefix=p.name + ".", suffix=".tmp", dir=str(p.parent)
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
            os.replace(tmp_path, p)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def _sync_delete(self, scope_id: str) -> None:
        try:
            self._path(scope_id).unlink()
        except FileNotFoundError:
            pass

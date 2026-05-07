import asyncio
import os
import tempfile
import unittest

from citation_kit.stores import InMemoryStore, JSONFileStore, SQLiteStore


class TestInMemoryStore(unittest.IsolatedAsyncioTestCase):
    async def test_save_load(self):
        s = InMemoryStore()
        await s.asave("scope-A", {"records": {"pmid:1": {"title": "P"}}, "turns": []})
        loaded = await s.aload("scope-A")
        self.assertEqual(loaded["records"]["pmid:1"]["title"], "P")

    async def test_load_missing_returns_none(self):
        s = InMemoryStore()
        self.assertIsNone(await s.aload("nope"))

    async def test_delete(self):
        s = InMemoryStore()
        await s.asave("X", {"a": 1})
        await s.adelete("X")
        self.assertIsNone(await s.aload("X"))

    async def test_isolation(self):
        s = InMemoryStore()
        await s.asave("A", {"a": 1})
        d = await s.aload("A")
        d["a"] = 999
        d2 = await s.aload("A")
        self.assertEqual(d2["a"], 1)  # mutating loaded copy doesn't change store


class TestJSONFileStore(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.s = JSONFileStore(self.tmp.name)

    async def asyncTearDown(self):
        self.tmp.cleanup()

    async def test_save_load(self):
        await self.s.asave("thread-uuid-1", {"key": "value", "count": 42})
        loaded = await self.s.aload("thread-uuid-1")
        self.assertEqual(loaded, {"key": "value", "count": 42})

    async def test_unsafe_scope_id(self):
        # Slashes in scope_id should not create subdirs
        await self.s.asave("a/b/c", {"x": 1})
        loaded = await self.s.aload("a/b/c")
        self.assertEqual(loaded, {"x": 1})
        # Verify only one file was created at the top level
        files = os.listdir(self.tmp.name)
        self.assertEqual(len(files), 1)

    async def test_unicode_scope(self):
        await self.s.asave("会话_42", {"中文": "ok"})
        loaded = await self.s.aload("会话_42")
        self.assertEqual(loaded, {"中文": "ok"})

    async def test_atomic_via_replace(self):
        # Just verify the save doesn't leave a tmp file behind
        await self.s.asave("X", {"big": "data" * 1000})
        files = os.listdir(self.tmp.name)
        self.assertEqual(len(files), 1)
        self.assertFalse(any(".tmp" in f for f in files))

    async def test_delete(self):
        await self.s.asave("X", {"a": 1})
        await self.s.adelete("X")
        self.assertIsNone(await self.s.aload("X"))
        await self.s.adelete("X")  # idempotent

    async def test_corrupt_file_returns_none(self):
        # Write a corrupt json and verify aload returns None instead of raising
        path = self.s._path("X")
        path.write_text("not json{{{", encoding="utf-8")
        self.assertIsNone(await self.s.aload("X"))


class TestSQLiteStore(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
        self.tmp.close()
        self.s = SQLiteStore(self.tmp.name)

    async def asyncTearDown(self):
        os.unlink(self.tmp.name)

    async def test_save_load(self):
        await self.s.asave("conv-1", {"records": {"pmid:1": {"title": "P"}}, "turns": []})
        loaded = await self.s.aload("conv-1")
        self.assertEqual(loaded["records"]["pmid:1"]["title"], "P")

    async def test_load_missing_returns_none(self):
        self.assertIsNone(await self.s.aload("nope"))

    async def test_overwrite(self):
        await self.s.asave("X", {"v": 1})
        await self.s.asave("X", {"v": 2})
        self.assertEqual((await self.s.aload("X"))["v"], 2)

    async def test_unicode_scope_and_data(self):
        await self.s.asave("会话_42", {"中文": "ok", "n": 42})
        loaded = await self.s.aload("会话_42")
        self.assertEqual(loaded["中文"], "ok")

    async def test_delete(self):
        await self.s.asave("X", {"a": 1})
        await self.s.adelete("X")
        self.assertIsNone(await self.s.aload("X"))
        await self.s.adelete("X")  # idempotent

    async def test_optimistic_locking_first_insert(self):
        # Initial insert: expected_version=0 succeeds
        ok = await self.s.asave_with_version("X", {"v": 1}, expected_version=0)
        self.assertTrue(ok)
        # Second insert with expected=0 must fail (already exists)
        ok2 = await self.s.asave_with_version("X", {"v": "boom"}, expected_version=0)
        self.assertFalse(ok2)
        self.assertEqual((await self.s.aload("X"))["v"], 1)

    async def test_optimistic_locking_cas(self):
        await self.s.asave("X", {"v": 1})
        data, ver = await self.s.aload_with_version("X")
        # Successful CAS with current version
        ok = await self.s.asave_with_version("X", {"v": 2}, expected_version=ver)
        self.assertTrue(ok)
        # Stale CAS with old version fails
        ok2 = await self.s.asave_with_version("X", {"v": 99}, expected_version=ver)
        self.assertFalse(ok2)
        self.assertEqual((await self.s.aload("X"))["v"], 2)

    async def test_in_memory(self):
        # `:memory:` works for ephemeral testing
        s = SQLiteStore(":memory:")
        await s.asave("k", {"v": 1})
        self.assertEqual((await s.aload("k"))["v"], 1)


if __name__ == "__main__":
    unittest.main()

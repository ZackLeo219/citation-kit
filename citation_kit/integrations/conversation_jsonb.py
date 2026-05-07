"""Embed registry data in an existing ``conversations.metadata`` JSONB column.

For projects that have a ``conversations`` table (e.g. bridge_agent) and
want the citation registry to live next to other per-conversation
metadata, FK-cascade naturally on conversation deletion, and share the
same transaction boundary as conversation writes.

Reference impl — copy into your project, adjust column / table names::

    class ConversationJSONBStore:
        def __init__(self, pool, *, table="conversations",
                     pk="id", json_col="metadata", json_key="citation_registry"):
            self.pool = pool
            self.table = table
            self.pk = pk
            self.json_col = json_col
            self.json_key = json_key

        async def aload(self, scope_id):
            async with self.pool.acquire() as c:
                row = await c.fetchrow(
                    f"SELECT {self.json_col} FROM {self.table} WHERE {self.pk} = $1",
                    int(scope_id),
                )
            if row is None:
                return None
            return ((row[self.json_col] or {}).get(self.json_key))

        async def asave(self, scope_id, data):
            import json
            async with self.pool.acquire() as c:
                await c.execute(f'''
                    UPDATE {self.table}
                    SET {self.json_col} = jsonb_set(
                        coalesce({self.json_col}, '{{}}'::jsonb),
                        '{{{self.json_key}}}',
                        $2::jsonb
                    )
                    WHERE {self.pk} = $1
                ''', int(scope_id), json.dumps(data))

        async def adelete(self, scope_id):
            async with self.pool.acquire() as c:
                await c.execute(f'''
                    UPDATE {self.table}
                    SET {self.json_col} = ({self.json_col} - $2)
                    WHERE {self.pk} = $1
                ''', int(scope_id), self.json_key)

Notes:
  * scope_id is converted to int — adjust if your PK type differs
  * If your conversations table doesn't exist yet (auto-create scope), bias
    toward PostgresStore (own table) rather than this pattern
  * To share the same transaction as a conversation write, use a
    transaction context from the caller side instead of pool.acquire()
"""

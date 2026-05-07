"""SQLAlchemy 2.0 async integration.

For projects already on SQLAlchemy that prefer one ORM session/transaction
boundary over raw asyncpg or sqlite calls.

Reference impl — copy into your project::

    from sqlalchemy import Column, String, JSON, Integer, DateTime, func
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.orm import declarative_base
    from sqlalchemy.future import select

    Base = declarative_base()

    class CitationRegistryRow(Base):
        __tablename__ = "citation_registry"
        scope_id = Column(String, primary_key=True)
        data = Column(JSON, nullable=False)
        version = Column(Integer, nullable=False, default=1)
        updated_at = Column(DateTime(timezone=True), server_default=func.now(),
                            onupdate=func.now())

    class SQLAlchemyStore:
        def __init__(self, session_factory):
            self.session_factory = session_factory  # async_sessionmaker

        async def aload(self, scope_id):
            async with self.session_factory() as s:
                row = await s.get(CitationRegistryRow, scope_id)
            return row.data if row else None

        async def asave(self, scope_id, data):
            async with self.session_factory() as s:
                row = await s.get(CitationRegistryRow, scope_id)
                if row is None:
                    row = CitationRegistryRow(scope_id=scope_id, data=data)
                    s.add(row)
                else:
                    row.data = data
                    row.version = (row.version or 0) + 1
                await s.commit()

        async def adelete(self, scope_id):
            async with self.session_factory() as s:
                row = await s.get(CitationRegistryRow, scope_id)
                if row is not None:
                    await s.delete(row)
                    await s.commit()

Notes:
  * Run Alembic migration (or ``Base.metadata.create_all``) once before use
  * For optimistic locking, use SQLAlchemy's ``mapper_args = {"version_id_col": version}``
  * To share a transaction with surrounding code, accept an open AsyncSession
    instead of session_factory and skip the ``async with``
"""

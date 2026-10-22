"""SQLAlchemy integration: an async engine plus request-scoped sessions.

SQLAlchemy stays the source of truth for ORM semantics; this module only
creates the engine and hands out sessions. Use Alembic for migrations;
``create_all()`` is a development convenience.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

try:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from sqlalchemy.orm import DeclarativeBase
except ImportError as exc:  # pragma: no cover
    raise ImportError("database support needs SQLAlchemy: pip install 'rational[db]'") from exc


class Model(DeclarativeBase):
    """Optional declarative base. Any SQLAlchemy declarative base works with ``Database``."""


class Database:
    def __init__(self, url: str, *, echo: bool = False, **engine_options: Any) -> None:
        self.url = url
        self.engine = create_async_engine(url, echo=echo, **engine_options)
        self.sessionmaker = async_sessionmaker(self.engine, expire_on_commit=False)

    def session(self) -> AsyncSession:
        """``async with db.session() as session: ...`` — commit explicitly."""
        return self.sessionmaker()

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[AsyncSession]:
        """A session inside a transaction: commits on success, rolls back on error."""
        async with self.sessionmaker() as session, session.begin():
            yield session

    async def create_all(self, base: type[DeclarativeBase] = Model) -> None:
        async with self.engine.begin() as conn:
            await conn.run_sync(base.metadata.create_all)

    async def dispose(self) -> None:
        await self.engine.dispose()

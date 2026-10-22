"""One engine for the app, and the declarative base for its tables."""

from sqlalchemy.orm import DeclarativeBase

from rational.backend import Database

import settings


class Base(DeclarativeBase):
    pass


database = Database(settings.DATABASE_URL)


async def create_tables() -> None:
    """Development convenience: use Alembic migrations in production."""
    await database.create_all(Base)

"""The entry table, and the shapes that cross the API and forms."""

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class EntryRow(Base):
    __tablename__ = "entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(40))
    message: Mapped[str] = mapped_column(String(280))
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))


class Entry(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    message: str


class SignForm(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    message: str = Field(min_length=1, max_length=280)

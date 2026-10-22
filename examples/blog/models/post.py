from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class Post(Base):
    """The table."""

    __tablename__ = "posts"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(120))
    summary: Mapped[str] = mapped_column(String(280), default="")
    body: Mapped[str] = mapped_column(Text, default="")
    tags: Mapped[str] = mapped_column(String(200), default="")  # comma-separated, lowercase
    published: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))


class PostOut(BaseModel):
    """A post as pages and the API see it, with its tags as a list."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    slug: str
    title: str
    summary: str
    body: str
    tags: list[str]
    published: bool
    created_at: datetime

    @field_validator("tags", mode="before")
    @classmethod
    def split_tags(cls, value: object) -> object:
        return [t.strip() for t in value.split(",") if t.strip()] if isinstance(value, str) else value


class PostIn(BaseModel):
    """What the editor (or the API) may submit."""

    title: str = Field(min_length=1, max_length=120)
    slug: str = Field(default="", max_length=80)
    summary: str = Field(default="", max_length=280)
    tags: str = Field(default="", max_length=200)
    body: str = ""
    published: bool = False

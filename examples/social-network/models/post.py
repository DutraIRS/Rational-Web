"""Posts and likes: the tables, and the shapes that cross the API and forms."""

from datetime import UTC, datetime

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base
from .member import Member

MAX_POST_LENGTH = 280


def _now() -> datetime:
    return datetime.now(UTC)


class Post(Base):
    __tablename__ = "posts"

    id: Mapped[int] = mapped_column(primary_key=True)
    author_id: Mapped[int] = mapped_column(ForeignKey("members.id", ondelete="CASCADE"), index=True)
    body: Mapped[str] = mapped_column(String(MAX_POST_LENGTH))
    created_at: Mapped[datetime] = mapped_column(default=_now, index=True)
    # lazy="raise": the author must be loaded explicitly (selectinload), so N+1 queries can't sneak in.
    author: Mapped[Member] = relationship(lazy="raise")


class Like(Base):
    __tablename__ = "likes"

    member_id: Mapped[int] = mapped_column(ForeignKey("members.id", ondelete="CASCADE"), primary_key=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("posts.id", ondelete="CASCADE"), primary_key=True, index=True)


class PostView(BaseModel):
    """A post as displayed: with its author and like count, and whether *you* liked it."""

    id: int
    body: str
    created_at: datetime
    author_handle: str
    author_name: str
    likes: int
    liked: bool


class ComposeForm(BaseModel):
    body: str = Field(max_length=MAX_POST_LENGTH)

    @field_validator("body")
    @classmethod
    def not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Write something first")
        return value.strip()

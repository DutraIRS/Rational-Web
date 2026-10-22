from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class Comment(Base):
    """The table. Deleting a post deletes its comments."""

    __tablename__ = "comments"

    id: Mapped[int] = mapped_column(primary_key=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("posts.id", ondelete="CASCADE"), index=True)
    author: Mapped[str] = mapped_column(String(60))
    body: Mapped[str] = mapped_column(String(2000))
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))


class CommentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    author: str
    body: str
    created_at: datetime


class CommentIn(BaseModel):
    """What the comment form may submit."""

    author: str = Field(min_length=1, max_length=60)
    body: str = Field(min_length=1, max_length=2000)

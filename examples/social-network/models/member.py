"""Members and follows: the tables, and the shapes that cross the API and forms."""

import re
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base

HANDLE = re.compile(r"^[a-z0-9_]{3,20}$")


def _now() -> datetime:
    return datetime.now(UTC)


class Member(Base):
    __tablename__ = "members"

    id: Mapped[int] = mapped_column(primary_key=True)
    handle: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(60))
    bio: Mapped[str] = mapped_column(String(160), default="")
    created_at: Mapped[datetime] = mapped_column(default=_now)


class Follow(Base):
    __tablename__ = "follows"

    follower_id: Mapped[int] = mapped_column(ForeignKey("members.id", ondelete="CASCADE"), primary_key=True)
    followee_id: Mapped[int] = mapped_column(ForeignKey("members.id", ondelete="CASCADE"), primary_key=True)


class MemberOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    handle: str
    name: str
    bio: str


class ProfileView(BaseModel):
    handle: str
    name: str
    bio: str
    posts: int
    followers: int
    following: int
    followed_by_me: bool
    is_me: bool


class JoinForm(BaseModel):
    handle: str
    name: str = Field(min_length=1, max_length=60)

    @field_validator("handle")
    @classmethod
    def valid_handle(cls, value: str) -> str:
        value = value.strip().lstrip("@").lower()
        if not HANDLE.match(value):
            raise ValueError("Use 3 to 20 lowercase letters, digits or underscores")
        return value

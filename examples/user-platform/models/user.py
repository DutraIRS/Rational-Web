from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict
from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base

ROLES = ("member", "admin")


class User(Base):
    """The table."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(60))
    bio: Mapped[str] = mapped_column(String(280), default="")
    role: Mapped[str] = mapped_column(String(10), default="member")
    password_hash: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))


class FirstAccount(Base):
    """One row at most: whoever inserts it is the administrator. The primary key lets only one insert
    succeed, however many accounts are created at the same moment."""

    __tablename__ = "first_account"

    id: Mapped[int] = mapped_column(primary_key=True)  # always 1
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))


class UserOut(BaseModel):
    """A user as everyone else sees them: never the password hash."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    name: str
    bio: str
    role: str
    created_at: datetime

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

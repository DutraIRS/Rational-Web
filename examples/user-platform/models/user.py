from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict
from sqlalchemy import String
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

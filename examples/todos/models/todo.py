from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class Todo(Base):
    """The table."""

    __tablename__ = "todos"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner: Mapped[str] = mapped_column(String(40), index=True)
    title: Mapped[str] = mapped_column(String(200))
    done: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))


class TodoOut(BaseModel):
    """A todo as the rest of the app and the API see it."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    done: bool


class NewTodo(BaseModel):
    """What the "new todo" form may submit."""

    title: str = Field(min_length=1, max_length=200)

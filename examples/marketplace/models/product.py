from typing import Literal

from pydantic import BaseModel, ConfigDict
from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base

Sort = Literal["name", "price-asc", "price-desc"]
SORTS: list[tuple[str, str]] = [
    ("name", "Name"),
    ("price-asc", "Price: low to high"),
    ("price-desc", "Price: high to low"),
]


class Product(Base):
    """The table. Prices are integer cents."""

    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    category: Mapped[str] = mapped_column(String(40), index=True)
    emoji: Mapped[str] = mapped_column(String(8))
    description: Mapped[str] = mapped_column(String(400), default="")
    price_cents: Mapped[int]
    stock: Mapped[int] = mapped_column(default=0)


class ProductOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    category: str
    emoji: str
    description: str
    price_cents: int
    stock: int

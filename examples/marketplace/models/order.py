from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    customer: Mapped[str] = mapped_column(String(40), index=True)
    address: Mapped[str] = mapped_column(String(400))
    total_cents: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))
    # lazy="raise": touching an unloaded relationship is an error, so N+1 queries can't sneak in.
    lines: Mapped[list["OrderLine"]] = relationship(back_populates="order", cascade="all, delete-orphan", lazy="raise")


class OrderLine(Base):
    __tablename__ = "order_lines"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    name: Mapped[str] = mapped_column(String(80))  # copied: the order keeps its history if the product changes
    quantity: Mapped[int]
    price_cents: Mapped[int]
    order: Mapped[Order] = relationship(back_populates="lines", lazy="raise")


class OrderLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    product_id: int
    name: str
    quantity: int
    price_cents: int


class OrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    address: str
    total_cents: int
    created_at: datetime
    lines: list[OrderLineOut]


class CheckoutForm(BaseModel):
    address: str = Field(min_length=10, max_length=400)

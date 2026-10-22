"""Browsing is public; checkout and order history need a signed-in customer.

The ``@remote`` methods are also a JSON API under ``/api/shop/...``.
"""

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from rational import FieldError, NotFound, RemoteError
from rational.backend import Service, remote

from models import Order, OrderLine, OrderOut, Product, ProductOut, Sort

ORDERING = {
    "name": Product.name,
    "price-asc": Product.price_cents,
    "price-desc": Product.price_cents.desc(),
}


class ShopService(Service):
    """Catalog, checkout and orders."""

    @remote(method="GET")
    async def products(self, q: str = "", category: str = "", sort: Sort = "name") -> list[ProductOut]:
        """Search the catalog by name, optionally within a category."""
        query = select(Product).order_by(ORDERING.get(sort, Product.name), Product.id)
        if q.strip():
            query = query.where(Product.name.ilike(f"%{q.strip()}%"))  # a bound parameter: no SQL injection
        if category:
            query = query.where(Product.category == category)
        async with self.db.session() as db:
            return [ProductOut.model_validate(p) for p in await db.scalars(query)]

    @remote(method="GET")
    async def categories(self) -> list[str]:
        """Every category, alphabetically."""
        async with self.db.session() as db:
            return list(await db.scalars(select(Product.category).distinct().order_by(Product.category)))

    @remote(method="GET")
    async def product(self, product_id: int) -> ProductOut:
        """One product."""
        async with self.db.session() as db:
            product = await db.get(Product, product_id)
        if product is None:
            raise NotFound("No such product")
        return ProductOut.model_validate(product)

    async def products_by_id(self, ids: list[int]) -> dict[int, ProductOut]:
        if not ids:
            return {}
        async with self.db.session() as db:
            rows = await db.scalars(select(Product).where(Product.id.in_(ids)))
            return {p.id: ProductOut.model_validate(p) for p in rows}

    @remote(auth="required")
    async def checkout(self, items: dict[int, int], address: str) -> OrderOut:
        """Place an order for ``{product_id: quantity}``. Stock is checked and reserved atomically."""
        items = {pid: qty for pid, qty in items.items() if qty > 0}
        if not items:
            raise RemoteError("Your cart is empty")
        if len(address.strip()) < 10:
            raise FieldError("address", "Please enter a full shipping address")
        async with self.db.transaction() as db:  # all or nothing: any error below rolls everything back
            products = {p.id: p for p in await db.scalars(select(Product).where(Product.id.in_(items)))}
            order = Order(customer=self.user, address=address.strip(), total_cents=0, lines=[])
            for product_id, quantity in items.items():
                product = products.get(product_id)
                if product is None:
                    raise RemoteError("A product in your cart is no longer available")
                if product.stock < quantity:
                    raise RemoteError(f"Only {product.stock} left of “{product.name}”")
                product.stock -= quantity
                order.lines.append(
                    OrderLine(
                        product_id=product.id,
                        name=product.name,
                        quantity=quantity,
                        price_cents=product.price_cents,
                    )
                )
                order.total_cents += quantity * product.price_cents
            db.add(order)
            await db.flush()
            return OrderOut.model_validate(order)

    @remote(method="GET", auth="required")
    async def my_orders(self) -> list[OrderOut]:
        """Your orders, newest first."""
        query = (
            select(Order)
            .where(Order.customer == self.user)
            .options(selectinload(Order.lines))  # one extra query for all lines, not one per order
            .order_by(Order.id.desc())
        )
        async with self.db.session() as db:
            return [OrderOut.model_validate(o) for o in await db.scalars(query)]

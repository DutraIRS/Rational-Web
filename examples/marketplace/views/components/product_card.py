from rational import Badge, Button, Card, Heading, Link, Row, Spacer, Style, Text

from .cart import CartAware
from models import ProductOut, price
from views.styles import PRODUCT_CARD, PRODUCT_TILE


def StockBadge(product: ProductOut):  # noqa: N802 - a function component
    if product.stock == 0:
        return Badge("Sold out", tone="danger")
    if product.stock <= 3:
        return Badge(f"Only {product.stock} left", tone="warning")
    return Badge("In stock", tone="success")


class ProductCard(CartAware):
    product: ProductOut

    def add_one(self):
        self.add(self.product)

    def render(self):
        p = self.product
        in_cart = self.quantity(p.id)
        can_add = in_cart < p.stock
        return Card(
            Link(Text(p.emoji, aria_hidden="true", style=PRODUCT_TILE), href=f"/products/{p.id}", aria_label=p.name),
            Row(Badge(p.category), StockBadge(p), gap="xs", wrap=True),
            Heading(Link(p.name, href=f"/products/{p.id}", style=Style(color="on_surface")), level=3),
            Spacer(),
            Row(
                Text(price(p.price_cents), weight=700, size="lg"),
                Spacer(),
                Button(
                    f"In cart ({in_cart})" if in_cart and not can_add else "Add to cart",
                    size="sm",
                    variant="primary" if can_add else "secondary",
                    disabled=not can_add,
                    on_click=self.add_one,
                    aria_label=f"Add {p.name} to cart",
                ),
            ),
            Text(f"{in_cart} in your cart", size="sm", muted=True) if in_cart else None,
            style=PRODUCT_CARD,
        )

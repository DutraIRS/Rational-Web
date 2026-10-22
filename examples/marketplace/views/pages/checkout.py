"""The cart and checkout."""

from rational import (
    Button,
    ButtonLink,
    Card,
    Column,
    Form,
    Heading,
    Link,
    Page,
    RemoteError,
    Router,
    Row,
    Spacer,
    State,
    Text,
    Textarea,
    h,
    js,
)

from models import CheckoutForm, ProductOut, price
from services import ShopService
from views.components import CartAware, Shell
from views.styles import CART_LINE, CART_LINES, CART_PANEL, FLAT_CARD, LINE_TOTAL, SUMMARY

router = Router()


@router.page("/cart")
class CartPage(CartAware, Page):
    title = "Cart · Rational Market"
    products = State(factory=dict)
    problem = State("")

    async def mount(self):
        self.products = await self.use(ShopService).products_by_id(list(self.cart_items()))

    def change(self, product: ProductOut, quantity: int):
        return lambda: self.set_quantity(product, quantity)

    async def place_order(self, form: CheckoutForm):
        try:
            order = await self.use(ShopService).checkout(self.cart_items(), form.address)
        except RemoteError as error:  # e.g. someone else just bought the last one
            self.problem = error.message
            self.products = await self.use(ShopService).products_by_id(list(self.cart_items()))
            return
        self.empty_cart()
        self.navigate(f"/orders?placed={order.id}")

    def line(self, product: ProductOut, quantity: int):
        return h(
            "li",
            Text(product.emoji, aria_hidden="true", size="2xl"),
            Column(
                Link(product.name, href=f"/products/{product.id}"),
                Text(price(product.price_cents), muted=True, size="sm"),
                gap=0,
            ),
            Spacer(),
            Row(
                Button(
                    "−",
                    variant="outline",
                    size="sm",
                    aria_label=f"One less {product.name}",
                    on_click=self.change(product, quantity - 1),
                ),
                Text(str(quantity), tag="span", weight=700, aria_label=f"{quantity} of {product.name}"),
                Button(
                    "+",
                    variant="outline",
                    size="sm",
                    aria_label=f"One more {product.name}",
                    disabled=quantity >= product.stock,
                    on_click=self.change(product, quantity + 1),
                ),
                gap="xs",
            ),
            Text(price(product.price_cents * quantity), weight=700, style=LINE_TOTAL),
            Button(
                "Remove",
                variant="ghost",
                size="sm",
                aria_label=f"Remove {product.name}",
                on_click=[js.confirm(f"Remove {product.name} from your cart?"), self.change(product, 0)],
            ),
            key=product.id,
            style=CART_LINE,
        )

    def render(self):
        lines = [(self.products[pid], qty) for pid, qty in self.cart_items().items() if pid in self.products]
        if not lines:
            return Shell(
                Heading("Your cart", level=1),
                Card(Text("Your cart is empty."), ButtonLink("Browse the shop", href="/"), style=FLAT_CARD),
            )
        total = sum(product.price_cents * qty for product, qty in lines)
        if self.context.user:
            checkout = Form(
                Textarea("Shipping address", name="address", rows=3, required=True, autocomplete="street-address"),
                Button("Place order", type="submit", full_width=True),
                on_submit=self.place_order,
            )
        else:
            checkout = Column(
                Text("Sign in to check out. Your cart will be waiting."),
                ButtonLink("Sign in", href="/login?next=/cart", full_width=True),
            )
        summary = Card(
            Heading("Order summary", level=2),
            Row(Text("Total", weight=600), Spacer(), Text(price(total), size="xl", weight=800)),
            Text(self.problem, role="alert", color="danger") if self.problem else None,
            checkout,
            style=SUMMARY,
        )
        return Shell(
            Heading("Your cart", level=1),
            Row(
                Card(h("ul", *[self.line(p, q) for p, q in lines], style=CART_LINES), style=CART_PANEL),
                summary,
                align="start",
                gap="lg",
                collapse="narrow",
            ),
        )

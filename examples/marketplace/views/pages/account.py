"""Signing in and order history."""

from rational import (
    Badge,
    Button,
    Card,
    Column,
    Form,
    Heading,
    Input,
    Page,
    Router,
    Row,
    Spacer,
    State,
    Style,
    Text,
    h,
    local_path,
)

from models import SignInForm, price
from services import ShopService
from views.components import Shell
from views.styles import FLAT_CARD, NARROW_CARD, SUCCESS_CARD

router = Router()


@router.page("/login")
class Login(Page):
    title = "Sign in · Rational Market"
    next_url = State("/")

    def mount(self):
        self.next_url = local_path(self.request.query_params.get("next"))  # never another site

    def sign_in(self, form: SignInForm):
        # login() rotates the session *id* (against session fixation) but keeps its data: the cart stays.
        self.context.session.login(form.name.strip())
        self.navigate(self.next_url)

    def render(self):
        return Shell(
            Card(
                Heading("Sign in", level=1),
                Text("Demo sign-in: any name works.", muted=True),
                Form(
                    Input("Your name", name="name", required=True, autocomplete="name"),
                    Button("Continue", type="submit", full_width=True),
                    on_submit=self.sign_in,
                ),
                style=NARROW_CARD,
            )
        )


@router.page("/orders", auth="required")
class Orders(Page):
    title = "Your orders · Rational Market"
    orders = State(factory=list)
    placed = State(0)

    async def mount(self):
        placed = self.request.query_params.get("placed", "")
        self.placed = int(placed) if placed.isdigit() else 0
        self.orders = await self.use(ShopService).my_orders()

    def render(self):
        cards = [
            Card(
                Row(
                    Heading(f"Order #{order.id}", level=3),
                    Badge("just placed", tone="success") if order.id == self.placed else None,
                    Spacer(),
                    Text(f"{order.created_at:%b %d, %Y}", muted=True, size="sm"),
                ),
                h(
                    "ul",
                    *[
                        h("li", f"{line.quantity} × {line.name}, {price(line.price_cents)} each")
                        for line in order.lines
                    ],
                    style=Style(margin=0, padding_left="lg"),
                ),
                Row(
                    Text(f"Ships to: {order.address}", muted=True, size="sm"),
                    Spacer(),
                    Text(price(order.total_cents), weight=800),
                ),
                key=order.id,
                style=FLAT_CARD | Style(gap="sm"),
            )
            for order in self.orders
        ]
        banner = (
            Card(Text("Thank you! Your order is confirmed.", weight=600), role="status", style=SUCCESS_CARD)
            if self.placed
            else None
        )
        return Shell(
            Heading("Your orders", level=1),
            banner,
            Column(*cards, gap="md") if cards else Text("No orders yet.", muted=True),
        )

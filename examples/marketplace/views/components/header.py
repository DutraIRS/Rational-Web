from rational import Badge, Button, ButtonLink, Header, Link, Row, Spacer, Text

import settings
from .cart import CartAware
from views.styles import BRAND, HEADER


class ShopHeader(CartAware):
    """Reads the cart, so it re-renders by itself whenever any component changes it."""

    def sign_out(self):
        self.context.session.logout()  # also forgets the cart: it lives in the session
        self.navigate("/")

    def render(self):
        user = self.context.user
        count = self.item_count
        return Header(
            Row(
                Link(settings.SHOP_NAME, href="/", style=BRAND),
                Link("Shop", href="/"),
                Link("Orders", href="/orders") if user else None,
                Spacer(),
                Text(f"Hi, {user}", muted=True, size="sm") if user else None,
                Button("Sign out", variant="ghost", size="sm", on_click=self.sign_out) if user else None,
                Link("Sign in", href="/login") if not user else None,
                ButtonLink(
                    "Cart ",
                    Badge(str(count), tone="primary" if count else "neutral"),
                    href="/cart",
                    variant="outline",
                    size="sm",
                    aria_label=f"Cart, {count} item{'s' if count != 1 else ''}",
                ),
                gap="md",
                wrap=True,
            ),
            style=HEADER,
        )

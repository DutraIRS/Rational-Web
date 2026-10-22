from rational import Card, Component, h

from models import Order
from views.styles import CELL, HEADER_CELL, SCROLL_X, TABLE

COLUMNS = ("Order", "Customer", "Region", "Total")


class RecentOrders(Component):
    """A table that scrolls horizontally on small screens instead of breaking the layout."""

    orders: list[Order]

    def render(self):
        head = h("tr", *[h("th", label, scope="col", style=HEADER_CELL) for label in COLUMNS])
        body = [
            h(
                "tr",
                *[h("td", value, style=CELL) for value in (o.number, o.customer, o.region, f"${o.total:,}")],
                key=o.number,
            )
            for o in self.orders
        ]
        table = h("table", h("thead", head), h("tbody", *body), style=TABLE)
        return Card(h("div", table, style=SCROLL_X), title="Recent orders")

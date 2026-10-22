from rational import Button, Column, Component, Link, Nav, Row, Spacer, Text, js

from views.styles import NAV_LINK, NAV_LIST, SIDEBAR

SECTIONS = ("Overview", "Orders", "Customers", "Settings")


class Sidebar(Component):
    """Beside the content on desktop and above it on narrow screens (see ``SIDEBAR``).
    The theme buttons run in the browser with ``js.set_theme``: no server round trip."""

    def render(self):
        links = [
            Link(label, href="#", style=NAV_LINK, aria_current="page" if label == "Overview" else None)
            for label in SECTIONS
        ]
        themes = [
            Button(mode.capitalize(), size="sm", variant="outline", on_click=js.set_theme(mode))
            for mode in ("light", "dark", "system")
        ]
        return Nav(
            Text("◆ Acme", weight=700, size="lg"),
            Column(*links, gap="xs", style=NAV_LIST),
            Spacer(),
            Text("Theme", muted=True, size="sm"),
            Row(*themes, gap="xs", wrap=True),
            aria_label="Main",
            style=SIDEBAR,
        )

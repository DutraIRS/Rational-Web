from rational import Button, Component, Container, Header, Link, Nav, Row, Spacer, Style, Text, js

from content import PROFILE
from views.styles import STICKY_HEADER, WIDTH

ANCHORS = [
    ("about", "About"),
    ("experience", "Experience"),
    ("skills", "Skills"),
    ("projects", "Projects"),
    ("contact", "Contact"),
]


class SiteHeader(Component):
    """Sticks to the top while scrolling. The links jump to sections; on phones they are hidden
    (the page is short enough to scroll). The theme toggle runs entirely in the browser."""

    def render(self):
        links = Nav(
            Row(*[Link(label, href=f"#{anchor}") for anchor, label in ANCHORS], gap="md", wrap=True),
            aria_label="Sections",
            style=Style(viewport={"mobile": Style(display="none")}),
        )
        return Header(
            Container(
                Row(
                    Text(PROFILE.name, weight=800, tag="span"),
                    Spacer(),
                    links,
                    Button("◐", variant="ghost", size="sm", aria_label="Toggle dark mode", on_click=js.toggle_theme()),
                    gap="md",
                ),
                max_width=WIDTH,
            ),
            style=STICKY_HEADER,
        )

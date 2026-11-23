from rational import Button, Component, Container, Header, Link, Nav, Row, Spacer, Style, Text, h, js

from content import PROFILE
from views.styles import STICKY_HEADER, WIDTH

ANCHORS = [
    ("about", "About"),
    ("experience", "Experience"),
    ("skills", "Skills"),
    ("projects", "Projects"),
    ("contact", "Contact"),
]


def theme_icon():
    """A half-filled circle, drawn rather than typed: the "◐" character renders tiny or not at all in
    the fonts many Linux desktops have. currentColor keeps it in the theme's text colour."""
    return h(
        "svg",
        h("circle", cx="8", cy="8", r="6.5", fill="none", stroke="currentColor", stroke_width="1.5"),
        h("path", d="M8 1.5a6.5 6.5 0 0 0 0 13z", fill="currentColor"),
        viewBox="0 0 16 16",
        width="16",
        height="16",
        aria_hidden="true",
        focusable="false",
    )


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
                    Button(
                        theme_icon(),
                        variant="ghost",
                        size="sm",
                        aria_label="Toggle dark mode",
                        on_click=js.toggle_theme(),
                    ),
                    gap="md",
                ),
                max_width=WIDTH,
            ),
            style=STICKY_HEADER,
        )

"""A function component: a plain function returning nodes. No state and no identity, so it's the
lightest way to share markup."""

from rational import Column, Container, Footer, Header, Link, Row, Spacer, Text

import settings
from views.styles import BRAND, FOOTER, HEADER, MAIN, WIDTH


def Shell(*content, admin: bool = False):  # noqa: N802 - capitalized like the built-in primitives
    """Header, main column and footer around a page's content."""
    return Column(
        Header(
            Container(
                Row(
                    Link(settings.BLOG_TITLE, href="/", style=BRAND),
                    Spacer(),
                    Link("Admin", href="/admin") if admin else None,
                    Link("RSS", href="/feed.xml"),
                    Link("API", href="/api/docs"),
                    gap="md",
                ),
                max_width=WIDTH,
            ),
            style=HEADER,
        ),
        Container(*content, tag="main", max_width=WIDTH, style=MAIN),
        Footer(Container(Text("Built with Rational Web.", muted=True, size="sm"), max_width=WIDTH), style=FOOTER),
        gap=0,
    )

from rational import Avatar, ButtonLink, Column, Component, Heading, Link, Row, Text

from content import PROFILE
from views.styles import HERO, PROSE


class Hero(Component):
    """Who, what, where, and the two things a visitor most likely wants to do."""

    def render(self):
        return Row(
            Avatar(PROFILE.name, size=120),
            Column(
                Heading(PROFILE.name, level=1),
                Text(PROFILE.role, size="xl", color="primary", weight=600),
                Text(PROFILE.location, muted=True),
                Text(PROFILE.summary, style=PROSE),
                Row(
                    ButtonLink("Get in touch", href="#contact"),
                    ButtonLink("See projects", href="#projects", variant="outline"),
                    *[Link(link.label, href=link.url, external=True) for link in PROFILE.links],
                    gap="md",
                    wrap=True,
                ),
                gap="sm",
            ),
            id="about",
            gap="xl",
            align="center",
            collapse="mobile",  # the avatar goes above the text on phones
            style=HERO,
        )

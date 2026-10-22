"""Header with navigation and the account menu; pages pass their content as children."""

from rational import Avatar, Button, Column, Component, Container, Header, Link, Row, Spacer, Text

from settings import NETWORK_NAME
from views.styles import MAIN, SHELL


class Shell(Component):
    """Header with navigation and the account menu; pages pass their content as children."""

    def sign_out(self):
        self.context.session.logout()
        self.navigate("/explore")

    def render(self):
        handle = self.context.user
        nav = [Link("Home", href="/"), Link("Explore", href="/explore")]
        if handle:
            nav.append(Link("Profile", href=f"/u/{handle}"))
            account = Row(
                Avatar(handle, size=30),
                Text(f"@{handle}", tag="span", weight=600),
                Button("Sign out", variant="ghost", size="sm", on_click=self.sign_out),
                gap="sm",
            )
        else:
            account = Link("Sign in", href="/login")
        return Column(
            Header(
                Container(
                    Row(Text(f"◉ {NETWORK_NAME}", weight=800, size="lg"), *nav, Spacer(), account, gap="md", wrap=True),
                    max_width=960,
                ),
                style=SHELL,
            ),
            Container(*self.children, tag="main", max_width=960, style=MAIN),
            gap=0,
        )

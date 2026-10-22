from rational import Avatar, Button, ButtonLink, Column, Component, Container, Header, Link, Row, Spacer, Text

from models import UserOut
from views.styles import HEADER, MAIN


class Shell(Component):
    """Page chrome: brand, navigation and the account menu. Pages pass their content as children."""

    def sign_out(self):
        self.context.session.logout()  # forgets the user and rotates the session id
        self.navigate("/login")

    def render(self):
        user: UserOut | None = self.context.user
        nav = [Link("Dashboard", href="/"), Link("Settings", href="/settings")] if user else []
        if user and user.is_admin:
            nav.append(Link("Admin", href="/admin"))
        if user:
            account = Row(
                Avatar(user.name, size=32),
                Text(user.name, tag="span", weight=600),
                Button("Sign out", variant="outline", size="sm", on_click=self.sign_out),
                gap="sm",
            )
        else:
            account = Row(Link("Sign in", href="/login"), ButtonLink("Create account", href="/signup", size="sm"))
        return Column(
            Header(
                Row(Text("◆ Platform", weight=800, size="lg"), *nav, Spacer(), account, wrap=True, gap="md"),
                style=HEADER,
            ),
            Container(*self.children, tag="main", max_width=880, style=MAIN),
            gap=0,
        )

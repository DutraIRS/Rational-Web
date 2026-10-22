"""Suggestions loaded in ``mount()``; following someone refreshes them and tells the page."""

from collections.abc import Awaitable, Callable

from rational import Avatar, Button, Card, Column, Component, Heading, Link, Row, Spacer, State, Style, Text

from services import SocialService


class WhoToFollow(Component):
    """Suggestions loaded in ``mount()``; following someone refreshes them and tells the page."""

    followed: Callable[[], Awaitable[None]]
    people = State(factory=list)

    async def mount(self):
        self.people = await self.use(SocialService).suggestions()

    async def follow(self, handle: str):
        await self.use(SocialService).toggle_follow(handle)
        self.people = await self.use(SocialService).suggestions()
        await self.followed()

    def render(self):
        rows = [
            Row(
                Avatar(person.name, size=32),
                Column(
                    Link(person.name, href=f"/u/{person.handle}", style=Style(font_weight=600)),
                    Text(f"@{person.handle}", muted=True, size="sm"),
                    gap=0,
                ),
                Spacer(),
                Button(
                    "Follow",
                    size="sm",
                    variant="outline",
                    aria_label=f"Follow @{person.handle}",
                    on_click=lambda handle=person.handle: self.follow(handle),
                ),
                key=person.handle,
                gap="sm",
            )
            for person in self.people
        ]
        return Card(
            Heading("Who to follow", level=3),
            *(rows or [Text("You follow everyone. Popular!", muted=True)]),
            style=Style(shadow="none", padding="md", gap="sm"),
        )

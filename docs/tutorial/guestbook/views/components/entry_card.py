"""One guestbook entry, with its like button."""

from rational import Avatar, Button, Card, Component, Row, State, Style, Text

from models import Entry
from views.styles import ACCENT


class EntryCard(Component):
    entry: Entry
    hearts = State(0)

    def like(self):
        self.hearts += 1

    def render(self):
        return Card(
            Text(self.entry.message, size="lg"),
            Row(
                Avatar(self.entry.name, size=28),
                Text(self.entry.name, muted=True, size="sm"),
                Button(
                    f"♥ {self.hearts}", variant="ghost", size="sm", on_click=self.like, style=Style(margin_left="auto")
                ),
            ),
            style=ACCENT,
        )

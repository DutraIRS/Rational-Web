"""Tutorial step 4: styles, a theme and a responsive layout."""

from dataclasses import dataclass, field
from itertools import count

from pydantic import BaseModel, Field

from rational import (
    App,
    Avatar,
    Button,
    Card,
    Component,
    Container,
    Form,
    Grid,
    Heading,
    Input,
    Page,
    Row,
    State,
    Style,
    Text,
    Textarea,
    js,
)

app = App(title="Guestbook", theme="soft")  # a preset: modern, minimal, soft or professional


_ids = count(1)


@dataclass(frozen=True)
class Entry:
    name: str
    message: str
    id: int = field(default_factory=lambda: next(_ids))


GUESTBOOK = [
    Entry("Ada", "What a lovely place!"),
    Entry("Grace", "Signed, sealed, compiled."),
]


class SignForm(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    message: str = Field(min_length=1, max_length=280)


QUOTE = Style(font_size="lg", line_height=1.6)  # styles are values: define them once, reuse them
ACCENT = Style(border_left="4px solid var(--rw-color-primary)", hover=Style(shadow="md"), transition=True)


class EntryCard(Component):
    entry: Entry
    hearts = State(0)

    def like(self):
        self.hearts += 1

    def render(self):
        return Card(
            Text(self.entry.message, style=QUOTE),
            Row(
                Avatar(self.entry.name, size=28),
                Text(self.entry.name, muted=True, size="sm"),
                Button(
                    f"♥ {self.hearts}", variant="ghost", size="sm", on_click=self.like, style=Style(margin_left="auto")
                ),
            ),
            style=ACCENT,
        )


@app.page("/")
class Home(Page):
    title = "Guestbook"
    entries = State(factory=list)

    def mount(self):
        self.entries = list(GUESTBOOK)

    def sign(self, form: SignForm):
        GUESTBOOK.insert(0, Entry(form.name, form.message))
        self.entries = list(GUESTBOOK)

    def render(self):
        return Container(
            Row(
                Heading("Guestbook", level=1),
                Button("Dark mode", variant="outline", size="sm", on_click=js.toggle_theme()),  # no server trip
                justify="between",
            ),
            Row(
                Card(
                    Form(
                        Input("Your name", name="name", required=True),
                        Textarea("Message", name="message", required=True, rows=4),
                        Button("Sign the guestbook", type="submit", full_width=True),
                        on_submit=self.sign,
                        key=f"form-{len(self.entries)}",
                    ),
                    style=Style(width=320, shrink=0, viewport={"mobile": Style(width="100%")}),
                ),
                # As many columns as fit, at least 240px each: responsive without media queries.
                Grid(*[EntryCard(entry=e, key=e.id) for e in self.entries], min_column_width=240),
                align="start",
                collapse="mobile",  # side by side on wider screens, stacked on phones
            ),
            tag="main",
            max_width=1000,
            style=Style(layout="vertical", gap="lg", padding_y="xl"),
        )


if __name__ == "__main__":
    app.run()

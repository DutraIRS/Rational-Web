"""Tutorial step 3: state, events and a validated form."""

from dataclasses import dataclass, field
from itertools import count

from pydantic import BaseModel, Field

from rational import (
    App,
    Button,
    Card,
    Column,
    Component,
    Container,
    Form,
    Heading,
    Input,
    Page,
    Row,
    State,
    Text,
    Textarea,
)

app = App(title="Guestbook")


_ids = count(1)


@dataclass(frozen=True)
class Entry:
    name: str
    message: str
    id: int = field(default_factory=lambda: next(_ids))


GUESTBOOK = [  # shared by every visitor, until the server restarts (step 5 adds a database)
    Entry("Ada", "What a lovely place!"),
    Entry("Grace", "Signed, sealed, compiled."),
]


class SignForm(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    message: str = Field(min_length=1, max_length=280)


class EntryCard(Component):
    entry: Entry
    hearts = State(0)  # each card has its own count

    def like(self):
        self.hearts += 1  # assigning state re-renders this card, and only this card

    def render(self):
        return Card(
            Text(self.entry.message),
            Row(
                Text(f"— {self.entry.name}", muted=True, size="sm"),
                Button(f"♥ {self.hearts}", variant="ghost", size="sm", on_click=self.like),
                justify="between",
            ),
        )


@app.page("/")
class Home(Page):
    title = "Guestbook"
    entries = State(factory=list)

    def mount(self):
        self.entries = list(GUESTBOOK)

    def sign(self, form: SignForm):  # the annotation validates the submitted form
        GUESTBOOK.insert(0, Entry(form.name, form.message))
        self.entries = list(GUESTBOOK)

    def render(self):
        return Container(
            Heading("Guestbook", level=1),
            Form(
                Input("Your name", name="name", required=True),
                Textarea("Message", name="message", required=True, rows=3),
                Button("Sign the guestbook", type="submit"),
                on_submit=self.sign,
                key=f"form-{len(self.entries)}",  # a new key after signing: a fresh, empty form
            ),
            Column(*[EntryCard(entry=e, key=e.id) for e in self.entries]),
            max_width=640,
        )


if __name__ == "__main__":
    app.run()

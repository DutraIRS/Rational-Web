"""Tutorial step 2: a component with props."""

from dataclasses import dataclass

from rational import App, Card, Column, Component, Container, Heading, Page, Text

app = App(title="Guestbook")


@dataclass(frozen=True)
class Entry:
    name: str
    message: str


ENTRIES = [
    Entry("Ada", "What a lovely place!"),
    Entry("Grace", "Signed, sealed, compiled."),
]


class EntryCard(Component):
    entry: Entry  # an annotated class attribute is a prop: EntryCard(entry=...)

    def render(self):
        return Card(
            Text(self.entry.message),
            Text(f"— {self.entry.name}", muted=True, size="sm"),
        )


@app.page("/")
class Home(Page):
    title = "Guestbook"

    def render(self):
        return Container(
            Heading("Guestbook", level=1),
            Column(*[EntryCard(entry=entry, key=i) for i, entry in enumerate(ENTRIES)]),
            max_width=640,
        )


if __name__ == "__main__":
    app.run()

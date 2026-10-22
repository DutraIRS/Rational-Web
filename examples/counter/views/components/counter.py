from rational import Button, Card, Component, Row, State, Text

from views.styles import COUNT


class Counter(Component):
    """A labelled counter. ``label`` and ``step`` are props; ``count`` is per-instance state."""

    label: str = "Clicks"
    step: int = 1
    count = State(0)

    def increment(self):
        self.count += self.step

    def reset(self):
        self.count = 0

    def render(self):
        return Card(
            Text(self.label, muted=True, size="sm"),
            Text(f"{self.count}", style=COUNT, aria_live="polite"),
            Row(
                Button(f"+{self.step}", on_click=self.increment),
                Button("Reset", variant="outline", on_click=self.reset, disabled=self.count == 0),
            ),
        )

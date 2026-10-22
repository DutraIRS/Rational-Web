from rational import Card, Component, Input, State, Text


class Greeter(Component):
    """Typing sends the (debounced) value to a typed handler; the greeting re-renders."""

    name = State("")

    def set_name(self, value: str):
        self.name = value.strip()[:40]

    def render(self):
        return Card(
            Input("Your name", placeholder="Ada", on_input=self.set_name, autocomplete="off"),
            Text(f"Hello, {self.name or 'stranger'}!"),
        )

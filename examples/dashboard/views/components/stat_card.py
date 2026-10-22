from rational import Card, Component, Style, Text


class StatCard(Component):
    """A KPI tile: label, value and the change against the previous period."""

    label: str
    value: str
    delta: float

    def render(self):
        up = self.delta >= 0
        return Card(
            Text(self.label, muted=True, size="sm", weight=600),
            Text(self.value, size="2xl", weight=700),
            Text(
                f"{'▲' if up else '▼'} {abs(self.delta):.1f}% vs previous period",
                size="sm",
                color="success" if up else "danger",
            ),
            style=Style(gap="xs"),
        )

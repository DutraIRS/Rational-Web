from rational import Card, Component, Style, Text, h

from views.styles import AMOUNT, BAR, BAR_LABEL, BAR_ROW, BAR_TRACK, CHART, CHART_LIST


class RegionChart(Component):
    """A bar chart made of plain elements. It adapts to its *own* width with a container query:
    in a narrow card the amounts are hidden, whatever the size of the screen."""

    data: dict[str, int]

    def render(self):
        top = max(self.data.values())
        rows = [
            h(
                "li",
                Text(region, size="sm", style=BAR_LABEL),
                h("div", h("div", style=BAR | Style(width=f"{value / top * 100:.0f}%")), style=BAR_TRACK),
                Text(f"${value:,}", size="sm", style=AMOUNT),
                style=BAR_ROW,
            )
            for region, value in sorted(self.data.items(), key=lambda kv: -kv[1])
        ]
        return Card(h("ul", *rows, role="list", style=CHART_LIST), title="Revenue by region", style=CHART)

from rational import Button, Column, Grid, Heading, Main, Page, Router, Row, Select, Spacer, State, Text

from models import PERIODS
from services import MetricsService
from views.components import RecentOrders, RegionChart, Sidebar, StatCard
from views.styles import MAIN

router = Router()

RANGE_OPTIONS = [(str(days), label) for days, label in PERIODS.items()]


@router.page("/")
class Overview(Page):
    title = "Dashboard · Rational Web"
    days = State("30")
    seed = State(0)

    def set_range(self, value: str):
        if value in dict(RANGE_OPTIONS):  # never trust the browser: ignore values that aren't options
            self.days = value

    def refresh(self):
        self.seed += 1

    def render(self):
        m = self.use(MetricsService).overview(int(self.days), self.seed)
        return Row(
            Sidebar(),
            Main(
                Row(
                    Column(Heading("Overview", level=1), Text("Sales performance at a glance", muted=True), gap="xs"),
                    Spacer(),
                    Select("Range", RANGE_OPTIONS, value=self.days, on_change=self.set_range, hide_label=True),
                    Button("Refresh", variant="secondary", on_click=self.refresh),
                    wrap=True,
                    align="end",
                ),
                # As many columns as fit, at least 200px wide each: responsive without media queries.
                Grid(
                    StatCard(label="Revenue", value=f"${m.revenue:,}", delta=12.4),
                    StatCard(label="Orders", value=f"{m.orders:,}", delta=4.1),
                    StatCard(label="Conversion", value=f"{m.conversion}%", delta=-0.6),
                    StatCard(label="Refunds", value=str(m.refunds), delta=-2.3),
                    min_column_width=200,
                ),
                Grid(RegionChart(data=m.by_region), RecentOrders(orders=m.recent), min_column_width=340),
                style=MAIN,
            ),
            align="stretch",
            gap=0,
            collapse="narrow",  # the sidebar moves above the content below 1024px
        )

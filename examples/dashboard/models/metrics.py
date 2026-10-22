from dataclasses import dataclass

PERIODS = {7: "Last 7 days", 30: "Last 30 days", 90: "Last 90 days"}
REGIONS = ("North", "South", "East", "West", "Online")


@dataclass(frozen=True)
class Order:
    number: str
    customer: str
    region: str
    total: int


@dataclass(frozen=True)
class Metrics:
    days: int
    revenue: int
    orders: int
    conversion: float
    refunds: int
    by_region: dict[str, int]
    recent: list[Order]

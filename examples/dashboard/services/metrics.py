import random

from rational import FieldError
from rational.backend import Service, remote

from models import PERIODS, REGIONS, Metrics, Order

CUSTOMERS = ("Ada", "Grace", "Alan", "Edsger", "Barbara")


class MetricsService(Service):
    """Sales metrics. A real app would query a database or a warehouse here."""

    @remote(method="GET")
    def overview(self, days: int = 30, seed: int = 0) -> Metrics:
        """Revenue, orders, conversion, refunds and recent orders for the last ``days`` days."""
        if days not in PERIODS:
            raise FieldError("days", f"Choose one of: {', '.join(map(str, PERIODS))}")
        rng = random.Random(days * 1000 + seed)  # deterministic fake numbers; a new seed changes them
        by_region = {region: rng.randint(4, 40) * days * 10 for region in REGIONS}
        recent = [
            Order(f"#{rng.randint(10_000, 99_999)}", rng.choice(CUSTOMERS), rng.choice(REGIONS), rng.randint(20, 900))
            for _ in range(6)
        ]
        return Metrics(
            days=days,
            revenue=sum(by_region.values()),
            orders=rng.randint(80, 140) * days,
            conversion=round(rng.uniform(1.5, 4.5), 2),
            refunds=rng.randint(0, 3) * days,
            by_region=by_region,
            recent=recent,
        )

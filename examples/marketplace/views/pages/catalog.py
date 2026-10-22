"""Browsing: the searchable catalog and the product page."""

from rational import (
    Badge,
    Button,
    ButtonLink,
    Card,
    Column,
    Grid,
    Heading,
    Input,
    Page,
    Router,
    Row,
    Select,
    State,
    Text,
)

from models import SORTS, price
from services import ShopService
from views.components import CartAware, ProductCard, Shell, StockBadge
from views.styles import FLAT_CARD, PRODUCT_TILE_LARGE, SEARCH

router = Router()


@router.page("/")
class Catalog(Page):
    title = "Rational Market"
    query = State("")
    category = State("")
    sort = State("name")
    products = State(factory=list)
    categories = State(factory=list)

    async def mount(self):
        self.categories = await self.use(ShopService).categories()
        await self.search()

    async def search(self):
        self.products = await self.use(ShopService).products(self.query, self.category, self.sort)

    async def set_query(self, value: str):  # debounced: one request after typing pauses
        self.query = value
        await self.search()

    async def set_category(self, value: str):
        self.category = value if value in self.categories else ""
        await self.search()

    async def set_sort(self, value: str):
        self.sort = value if value in dict(SORTS) else "name"
        await self.search()

    def render(self):
        filters = Row(
            Input(
                "Search",
                name="q",
                type="search",
                placeholder="Search products",
                value=self.query,
                on_input=self.set_query,
                hide_label=True,
                style=SEARCH,
            ),
            Select(
                "Category",
                [("", "All categories"), *self.categories],
                value=self.category,
                on_change=self.set_category,
                hide_label=True,
            ),
            Select("Sort by", SORTS, value=self.sort, on_change=self.set_sort, hide_label=True),
            wrap=True,
            align="start",
        )
        count = len(self.products)
        results = (
            Grid(*[ProductCard(product=p, key=p.id) for p in self.products], min_column_width=230)
            if self.products
            else Card(Text("No products match your search."), style=FLAT_CARD)
        )
        return Shell(
            Column(Heading("Shop", level=1), Text("Small things, made well.", muted=True), gap="xs"),
            filters,
            Text(f"{count} product{'s' if count != 1 else ''}", muted=True, size="sm", aria_live="polite"),
            results,
        )


@router.page("/products/{product_id}")
class ProductPage(CartAware, Page):
    product_id: int
    product = State(None)
    amount = State("1")

    async def mount(self):
        self.product = await self.use(ShopService).product(self.product_id)  # NotFound -> 404 page
        self.title = self.product.name

    def set_amount(self, value: str):
        self.amount = value

    def add_selected(self):
        self.add(self.product, int(self.amount) if self.amount.isdigit() else 1)

    def render(self):
        p = self.product
        available = p.stock - self.quantity(p.id)
        options = [str(n) for n in range(1, min(available, 10) + 1)]
        if options:
            buy = Row(
                Select(
                    "Quantity", options, value=self.amount if self.amount in options else "1", on_change=self.set_amount
                ),
                Button("Add to cart", on_click=self.add_selected),
                align="end",
            )
        else:
            buy = Text("You have all remaining stock in your cart." if p.stock else "Sold out.", muted=True)
        in_cart = self.quantity(p.id)
        return Shell(
            Row(
                Text(p.emoji, aria_hidden="true", style=PRODUCT_TILE_LARGE),
                Column(
                    Badge(p.category),
                    Heading(p.name, level=1),
                    Text(price(p.price_cents), size="2xl", weight=700),
                    StockBadge(p),
                    Text(p.description),
                    buy,
                    Row(
                        Text(f"{in_cart} in your cart.", size="sm"),
                        ButtonLink("Go to cart", href="/cart", variant="ghost", size="sm"),
                    )
                    if in_cart
                    else None,
                    gap="sm",
                ),
                gap="xl",
                align="start",
                collapse="mobile",
            ),
        )

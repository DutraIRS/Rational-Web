"""A demo catalog, inserted on the first start."""

from sqlalchemy import select

from models import Product, database

CATALOG = [
    # name, category, emoji, price in cents, stock, description
    ("Pour-over coffee kit", "Home", "☕", 3400, 12, "Glass dripper, filters and a gooseneck kettle."),
    ("Monstera plant", "Home", "🪴", 2900, 5, "A forgiving, fast-growing houseplant."),
    ("Soy candle", "Home", "🕯️", 1800, 30, "Cedar and fig, 40 hours of burn time."),
    ("Python in Practice", "Books", "📘", 3900, 8, "Patterns for writing clear, robust Python."),
    ("Designing Data Systems", "Books", "📗", 4500, 3, "Storage, streams and the trade-offs between them."),
    ("The Web, Rationally", "Books", "📙", 2500, 0, "Server-rendered apps without the irrational parts."),
    ("Mechanical keyboard", "Tech", "⌨️", 12900, 6, "Hot-swappable switches, aluminium case."),
    ("Noise-cancelling headphones", "Tech", "🎧", 19900, 4, "Thirty hours of quiet."),
    ("Wireless mouse", "Tech", "🖱️", 3900, 15, "Silent clicks, USB-C charging."),
    ("Day pack", "Outdoor", "🎒", 7900, 7, "Twenty litres, weatherproof."),
    ("Two-person tent", "Outdoor", "⛺", 24900, 2, "1.9 kg, sets up in three minutes."),
    ("Brass compass", "Outdoor", "🧭", 2200, 20, "Liquid-damped, lifetime warranty."),
]


async def seed_catalog() -> None:
    async with database.transaction() as db:
        if await db.scalar(select(Product.id).limit(1)) is not None:
            return  # only on an empty database
        for name, category, emoji, price_cents, stock, description in CATALOG:
            db.add(
                Product(
                    name=name,
                    category=category,
                    emoji=emoji,
                    price_cents=price_cents,
                    stock=stock,
                    description=description,
                )
            )

"""Marketplace: the composition root.

Run:  pip install "rational[db]"
      python app.py --dev     # hot reload, readable errors
      python app.py --prod    # production server
"""

from rational import App

import settings
from models import create_tables, database
from services import ShopService, seed_catalog
from views.pages import router
from views.styles import THEME

app = App(
    title=settings.SHOP_NAME,
    description="Catalog, checkout and orders.",
    theme=THEME,
    database=database,
    login_path="/login",
)
app.include(router)
app.service(ShopService)  # JSON API under /api/shop/..., docs at /api/docs
app.on_startup(create_tables)
app.on_startup(seed_catalog)

if __name__ == "__main__":
    app.run()

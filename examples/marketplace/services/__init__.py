"""The rules: search, checkout and orders. Also a JSON API (see /api/docs)."""

from .seed import seed_catalog
from .shop import ShopService

__all__ = ["ShopService", "seed_catalog"]

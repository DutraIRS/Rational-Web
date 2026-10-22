"""Every page of the shop, combined into one router for ``app.py``."""

from rational import Router

from . import account, catalog, checkout

router = Router()
router.include(catalog.router)
router.include(checkout.router)
router.include(account.router)

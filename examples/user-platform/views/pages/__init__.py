"""Every page of the app, combined into one router for ``app.py``."""

from rational import Router

from . import account, admin

router = Router()
router.include(account.router)
router.include(admin.router)

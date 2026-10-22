"""Every page of the app, combined into one router for ``app.py``."""

from rational import Router

from . import account, explore, home, profile

router = Router()
for module in (home, explore, profile, account):
    router.include(module.router)

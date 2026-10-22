Structuring a project
=====================

Small apps fit in one file. Anything bigger deserves a structure where each module has one job.
All the examples use this layout:

.. code-block:: text

   myapp/
   ├── README.md
   ├── app.py             # the composition root
   ├── settings.py        # settings, from the environment
   ├── models/            # database.py (engine + base) and one file per table group
   ├── services/          # one file per service: business rules (+ @remote API)
   ├── views/
   │   ├── styles/        # theme and shared Style values
   │   ├── components/    # reusable components
   │   └── pages/         # pages, declared on Routers
   └── tests/

Layers import across as absolute names (``from views.components import Shell``), and within a
layer as relatives (``from . import home``).

Routers
-------

A :class:`~rational.Router` records pages, services and startup hooks without needing the app,
so page modules never import ``app.py`` (which would be a circular import):

.. code-block:: python

   # views/pages/admin.py
   from rational import Page, Router

   router = Router(prefix="/admin")

   @router.page("/")                  # served at /admin
   class AdminHome(Page): ...

   @router.page("/users/{user_id}")   # served at /admin/users/{user_id}
   class AdminUser(Page):
       user_id: int

Routers nest with ``router.include(other)``; a ``views/pages/__init__.py`` typically combines them:

.. code-block:: python

   # views/pages/__init__.py
   from rational import Router
   from . import admin, public

   router = Router()
   router.include(public.router)
   router.include(admin.router)

The composition root
--------------------

``app.py`` is the only module that knows how the parts fit together:

.. code-block:: python

   from models import create_tables, database
   from services import AccountService, current_user
   from views.pages import router

   from rational import App

   app = App(title="My app", database=database, login_path="/login")
   app.authenticate(current_user)
   app.include(router)
   app.service(AccountService)       # expose its @remote methods under /api
   app.on_startup(create_tables)

   if __name__ == "__main__":
       app.run()

Run it from the project folder with ``python app.py --dev``. Hot reload watches every Python file
in the folder, including the packages.

Settings
--------

Read settings once, from the environment, with safe defaults for development:

.. code-block:: python

   # settings.py
   import os
   from pathlib import Path

   PROJECT_DIR = Path(__file__).resolve().parent
   DATABASE_URL = os.environ.get("DATABASE_URL", f"sqlite+aiosqlite:///{(PROJECT_DIR / 'app.db').as_posix()}")

Never commit secrets: read them from the environment in production.

Where code goes
---------------

``settings.py``
   Constants and environment settings, read once at import time.
``models/``
   ``database.py`` holds the engine and the declarative base; one file per table group, holding
   both the SQLAlchemy tables and the Pydantic shapes that cross the API and forms.
``services/``
   Every rule about your data: queries, ownership checks, transactions, ``FieldError`` and
   ``RemoteError``. Pages and the JSON API both call it, so the rules live in one place.
``views/components/``
   Presentation and interaction. Components call services through ``self.use(Service)``.
``views/pages/``
   Routing, loading data in ``mount()``, and composing components.
``views/styles/``
   The theme preset and shared ``Style`` values, so look decisions have one home.

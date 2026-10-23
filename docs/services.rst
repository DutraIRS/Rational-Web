Services, the API and databases
===============================

Services
--------

A :class:`~rational.backend.Service` groups server operations. It is bound to the current
request context (``self.user``, ``self.session``, ``self.db``).

.. code-block:: python

   from rational.backend import Service, remote

   @app.service
   class TodoService(Service):
       @remote(method="GET", auth="required")
       async def list_todos(self) -> list[TodoOut]: ...

       @remote(auth="required")
       async def add(self, title: str) -> TodoOut: ...

       async def _owned(self, session, todo_id: int) -> Todo: ...   # not exposed

Components call services **in-process**::

   todos = await self.use(TodoService).list_todos()

The JSON API
------------

Only ``@remote`` methods are reachable over HTTP, at
``{api_prefix}/{service}/{method}`` — ``/api/todo/list-todos`` and ``/api/todo/add``
above. Rational generates a Pydantic body model from the parameters, uses the return
annotation as the response model, and publishes everything in OpenAPI at ``/api/docs``.

* ``auth="required"`` rejects anonymous callers with 401.
* Requests carrying a session cookie must send the ``X-RW-CSRF`` header.
* Raise :class:`~rational.RemoteError` (or ``NotFound``, ``Forbidden``) for a user-facing
  error; any other exception becomes a generic 500 and is logged.
* ``GET`` is for safe, idempotent reads only.

From custom browser code: ``await rational.call("todo", "add", {title: "Write docs"})``.

Swagger UI
----------

Every app with services has interactive API documentation at ``/api/docs`` (the OpenAPI schema
is at ``/api/openapi.json``). Services appear as sections, named after the class without
``Service``, and their docstrings become descriptions. Requests sent from Swagger UI carry your
session cookie *and* its CSRF token, so "Try it out" works while you are signed in.

Set the API's title, description and version on the app, and turn the documentation off if you
don't want it public:

.. code-block:: python

   app = App(title="Shop", description="Catalog and orders.", version="1.2.0")
   app = App(api_docs=False)      # no /api/docs, no /api/openapi.json
   app = App(api_prefix="/v1")    # /v1/todo/add, /v1/docs

Errors users can fix
--------------------

``raise FieldError("email", "This email is already registered")`` from a service or handler
reports a problem with one form field. The browser shows the message under that field, exactly
like a validation error, and the API answers ``422`` with ``{"field", "message"}`` details.
``FieldError({"password": "...", "confirm": "..."})`` reports several fields at once.

Authentication
--------------

By default the authenticated principal is whatever you store with
``session.login(user)`` (which also rotates the session id). Replace it with your own::

   @app.authenticate
   async def current_user(ctx):
       token = ctx.request.headers.get("authorization")
       return await lookup(token)

Pages can require it: ``@app.page("/admin", auth="required")``, with
``App(login_path="/login")`` to redirect instead of answering 401.

Databases
---------

SQLAlchemy stays the source of truth for ORM semantics; Rational only creates the engine
and hands out sessions.

.. code-block:: python

   app = App(database="sqlite+aiosqlite:///app.db")   # or "postgresql+asyncpg://..."

   async with app.db.transaction() as session:   # commits, or rolls back on error
       session.add(Todo(title="x"))

   async with app.db.session() as session:       # commit explicitly
       ...

``rational.backend.Model`` is an optional declarative base; any base works.
``await app.db.create_all(Base)`` is a development convenience — use migrations
in production (below). Prefer explicit loading (``selectinload``) to avoid N+1 queries and lazy
loads outside a session.

Migrations
----------

``pip install "rational[migrations]"`` adds Alembic, wired to your app so there is no ``alembic.ini``.
Pass your base's metadata (``Database(url, metadata=Base.metadata)``; it defaults to
``rational.backend.Model.metadata``), then:

.. code-block:: console

   python -m rational db init app.py                                  # creates ./migrations
   python -m rational db revision app.py -m "add users" --autogenerate
   python -m rational db upgrade app.py                               # to head, or a revision
   python -m rational db downgrade app.py -1
   python -m rational db current app.py
   python -m rational db history app.py

Review the generated revision before applying it. Migrations run on their own short-lived engine, and
SQLite uses batch mode so column changes work. To migrate at startup, call
``await app.db.upgrade()`` from an ``on_startup`` hook (use a single process or a lock when several
workers start at once).

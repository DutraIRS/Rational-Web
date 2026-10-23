Serverless and ASGI hosts
=========================

An ``App`` is a plain ASGI application, so anything that can run ASGI can run it. This page lists
what to set up; none of the platform recipes below are exercised in this project's CI.

What works, what does not
-------------------------

* **Static pages plus services**: works anywhere. Export the pages (``python app.py --export site/``)
  and host the ``@remote`` services as an ``api_only`` app with ``cors_origins=`` (see :doc:`services`).
* **Interactive pages**: each event is a separate request, so they work on request-scoped platforms
  only with ``page_snapshots=`` and a shared session store (:doc:`running`). Every event then pays a
  store read and write.
* **Push (SSE, WebSocket)**: needs a connection that stays open. Most function platforms cap or
  forbid that; leave background tasks, ``Suspense`` and ``websocket=True`` off there.

Settings for short-lived functions
----------------------------------

.. code-block:: python

    app = App(
        api_only=True,                       # or keep pages and add page_snapshots=
        session_store=PersistentSessionStore(RedisSessionDriver(url=REDIS_URL)),
        database=Database(DATABASE_URL, serverless=True),   # no pooled connections between invocations
    )

``Database(serverless=True)`` uses SQLAlchemy's ``NullPool``. Put a connection proxy (pgbouncer, RDS
Proxy, Neon's pooler) in front of the database, otherwise many cold starts open many connections.
Import heavy optional packages lazily to keep cold starts short.

Adapters
--------

Wrap the app with the platform's ASGI adapter. ``app`` is the ASGI callable::

    # AWS Lambda behind API Gateway or a function URL (pip install mangum)
    from mangum import Mangum
    handler = Mangum(app, lifespan="auto")

    # Google Cloud Run, Azure Container Apps, Fly.io, Render, Railway: run it as a container
    #   uvicorn mypackage.web:app --host 0.0.0.0 --port $PORT

    # Vercel: expose ``app`` from api/index.py and route every path to it in vercel.json

    # Azure Functions: azure.functions.AsgiFunctionApp(app=app, http_auth_level=...)

Behind a platform that serves the app under a prefix or terminates TLS, follow the proxy notes in
:doc:`running` (``--root-path``, ``X-Forwarded-Proto``). Keep ``debug=False`` and consider ``App(csp=True)``.

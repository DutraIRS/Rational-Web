Running and deploying
=====================

Every app is started the same way:

.. code-block:: python

   if __name__ == "__main__":
       app.run()

Development
-----------

.. code-block:: console

   $ python app.py --dev

* **Hot reload** — a small supervisor restarts the app when a ``*.py`` file changes
  (``watchfiles`` if installed, otherwise polling). It works the same on Windows, macOS
  and Linux.
* **Live browser reload** — open pages reload themselves after each restart.
* **Readable errors** — a failing page shows the exception, the line of *your* code with
  context, a hint for common mistakes and the full traceback. Errors in event handlers
  appear as an in-page overlay.
* Binds to ``127.0.0.1``. Never expose dev mode: it shows source code.

``--dev`` is the default when no mode is given, unless ``RATIONAL_ENV=production``.

Production
----------

.. code-block:: console

   $ python app.py --prod
   $ PORT=8080 python app.py --prod --workers 1

One origin serves everything:

==================  ==========================================
``/``…              your pages
``/api/…``          ``@remote`` services, OpenAPI at ``/api/docs``
``/_rational/…``    runtime script, theme CSS (immutable, cache forever), events
==================  ==========================================

Production mode disables debug output, binds to ``$HOST`` (default ``0.0.0.0``) and
``$PORT`` (default 8000), trusts ``X-Forwarded-*`` from ``$FORWARDED_ALLOW_IPS``
(default ``127.0.0.1``) and hides the ``server`` header. Use ``--root-path /prefix``
when a proxy serves the app under a sub-path.

.. important::

   Page views (component state) live in process memory. Run one worker per container,
   or use sticky sessions when you run several (``--workers N`` prints a reminder).

Sessions across workers and restarts
------------------------------------

By default sessions live in process memory too, so a restart logs everyone out. Give the app a
persistent store and logins, CSRF tokens and API calls work on any worker and survive restarts::

    from rational import App, PersistentSessionStore, RedisSessionDriver

    app = App(session_store=PersistentSessionStore(RedisSessionDriver(url="redis://localhost:6379/0")))

Install the client with ``pip install "rational[redis]"``. Each request reads its session from Redis
(one round trip) and writes it back only if it changed. A change or logout on one worker is seen by
the others. What is stored is JSON: the CSRF token and ``session.data`` including the signed-in user,
so keep session values JSON-compatible (or pass ``serialize=`` and ``deserialize=``). It is never
pickled, because a shared store is a trust boundary. Match ``ttl=`` to ``App(session_ttl=...)``.

Limits: concurrent writes from different workers are last-write-wins, and
``State(scope="session")`` values and open pages are still worker-local, so interactive pages
still need sticky routing. Any other backend (a database, say) only has to implement
:class:`~rational.stores.SessionDriver`: four async methods, ``get``, ``set``, ``touch`` and ``delete``.

Client-side navigation
----------------------

By default every link is a full page load. ``App(client_nav=True)`` makes same-origin links swap
the page in place instead, with no reload and no flash::

    app = App(client_nav=True)

The browser fetches the next page's HTML, swaps the body, title, description and page styles,
updates the address bar and history, and moves focus to ``<main>`` (or the first ``<h1>``).
Back and forward work. ``self.navigate(url)`` and ``raise Redirect(url)`` navigate the same way.

Things that still do a normal load: links with ``target``, ``download``, ``rel="external"`` or
``data-rw-reload``, modified clicks (Ctrl, Shift, Alt, Cmd), other origins, and any response that
is not a Rational page. If a client-side navigation fails for any reason, the browser falls back
to a normal load. Two caveats:

* Scripts inside a page body are not re-run on navigation; put shared scripts in the layout's
  ``<head>`` or use ``window.rational``.
* The browser fires ``rw:navigating`` and ``rw:navigated`` events on ``document`` for analytics.

The old page's server-side view and background tasks stop when its stream closes and the page
expires. Static export ignores ``client_nav``.

.. _static-export:

Static export
-------------

A site made of static pages does not need a running server. Export it as plain HTML files
and host them anywhere (GitHub Pages, Netlify, S3, a CDN)::

   $ python app.py --export site/
   $ python app.py --export site/ --root-path /my-repo     # served under a sub-path

This writes ``site/index.html``, ``site/<path>/index.html``, ``site/_rational/theme.css``,
a ``404.html`` and a copy of every directory mounted with ``app.static``. Only pages that
work without a server are exported: those with no path parameters, no ``auth="required"``
and no interactivity (any page that loads the browser runtime, such as one with event handlers).
Everything else is listed as skipped with the reason, and the command exits non-zero if nothing could
be exported. The same export is available from code as :func:`rational.export.export_site`.

Request logging and tracing
---------------------------

Every HTTP response includes an ``X-Request-ID`` header. A valid ID supplied by the
caller is preserved; otherwise Rational generates one. The ``rational`` standard-library
logger emits structured ``LogRecord`` fields for request completion and event dispatch,
including the request ID and elapsed milliseconds. Slow page renders are logged at
``WARNING``; the default threshold is 100 ms.

.. code-block:: python

   app.logging.configure(
       request_id_header="X-Request-ID",
       slow_render_threshold_ms=75,
   )

To emit OpenTelemetry spans for requests, page renders and event dispatch, install
``rational[telemetry]``, configure an OpenTelemetry SDK provider/exporter in the host
application, then enable tracing:

.. code-block:: python

   app.logging.configure(opentelemetry=True)

The framework does not install or configure an exporter, so the host application retains
control over where telemetry is sent.

API-only apps and a static front end
------------------------------------

A Rational app can be just an API. ``api_only=True`` serves ``@remote`` services and nothing
else (no pages, no runtime script, no event or stream endpoints). Because there is no session
cookie, callers authenticate with a token, and CSRF does not apply::

    app = App(api_only=True, cors_origins=["https://my-site.example"])

    @app.authenticate
    def bearer(ctx):
        header = ctx.request.headers.get("authorization", "")
        return verify_token(header.removeprefix("Bearer ")) if header.startswith("Bearer ") else None

    @app.service
    class Notes(Service):
        @remote(auth="required")
        def mine(self) -> list[Note]: ...

``cors_origins`` allows those browser origins to call the API prefix (and only the API prefix).
Credentials are never allowed cross-origin, so the session cookie is not sent: use the bearer
token. Use ``["*"]`` for a public API. OpenAPI is at ``/api/openapi.json`` for generating clients.

Pair this with :ref:`static export <static-export>` for the pages: ``--export`` the site to any
static host and run the API anywhere that serves ASGI. The pages call the API with ``fetch``
(or ``rational.call`` on an interactive page).

Other deployment strategies
---------------------------

Any ASGI server
   ``App`` is an ASGI application::

      uvicorn app:app --host 0.0.0.0 --port 8000 --proxy-headers
      gunicorn app:app -k uvicorn.workers.UvicornWorker -w 1

The module entry point
   Run an app without a ``__main__`` block, or with an import string::

      python -m rational path/to/app.py --prod
      python -m rational mypackage.web:app --prod --workers 2

Inside an existing FastAPI application
   ::

      api = FastAPI()
      api.mount("/app", rational_app)          # or add routes to rational_app.fastapi

Behind a reverse proxy / CDN
   Terminate TLS at the proxy, forward ``X-Forwarded-Proto`` so cookies get ``Secure``,
   and cache ``/_rational/*.js|css`` aggressively (their URLs are content-hashed).

Containers
   .. code-block:: dockerfile

      FROM python:3.13-slim
      WORKDIR /srv
      COPY . .
      RUN pip install --no-cache-dir "rational[db]" .
      ENV RATIONAL_ENV=production
      CMD ["python", "app.py", "--prod"]

Content Security Policy
   ``App(csp=True)`` sends a strict policy with a per-response nonce. No inline
   ``style=`` attributes or inline scripts are generated.

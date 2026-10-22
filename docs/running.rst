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

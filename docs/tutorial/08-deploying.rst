8. Deploying
============

The same ``app.py`` runs in production:

.. code-block:: console

   $ python app.py --prod

Production mode serves everything from one origin: your pages at ``/``, the JSON API under
``/api`` (with Swagger UI at ``/api/docs``) and Rational's own assets under ``/_rational``. It
turns off debug output, listens on ``$HOST`` and ``$PORT``, and trusts ``X-Forwarded-*``
headers from your reverse proxy.

Point the database at a real server through the environment:

.. code-block:: console

   $ DATABASE_URL="postgresql+asyncpg://user:pass@db/guestbook" python app.py --prod

A container image:

.. code-block:: dockerfile

   FROM python:3.13-slim
   WORKDIR /srv
   COPY . .
   RUN pip install --no-cache-dir "rational[db]" asyncpg
   ENV RATIONAL_ENV=production
   CMD ["python", "app.py", "--prod"]

.. important::

   Live page state is kept in the server's memory. Run one process per container, or enable
   sticky sessions when you run several.

:doc:`../running` covers the other options: any ASGI server, ``python -m rational``,
mounting inside an existing FastAPI app, sub-paths behind a proxy and Content Security Policy.

That's it: you built, tested and shipped a full-stack app in Python. Explore the
:doc:`../examples/index` next, from a CV site to a marketplace.

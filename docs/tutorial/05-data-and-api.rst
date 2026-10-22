5. A database, a service and an API
===================================

Messages vanish when the server restarts. Let's store them with SQLAlchemy:

The complete file is at the end of this page; here are the new parts.

The table
---------

Plain SQLAlchemy 2.0: a declarative base and a mapped class. ``App(database=...)`` creates the
async engine, and ``create_tables`` runs at startup. In production you would use Alembic
migrations instead.

.. literalinclude:: steps/step5.py
   :pyobject: EntryRow

.. literalinclude:: steps/step5.py
   :pyobject: create_tables

The service
-----------

A :class:`~rational.backend.Service` holds the operations on your data:

.. literalinclude:: steps/step5.py
   :pyobject: GuestbookService

Pages call it in-process, with ``self.use(...)``:

.. literalinclude:: steps/step5.py
   :pyobject: Home

The same methods marked ``@remote`` are **also** a JSON API, with request and response
validation from your type hints:

.. code-block:: console

   $ curl http://127.0.0.1:8000/api/guestbook/entries
   [{"id": 1, "name": "Ada", "message": "Hello!"}]

Open http://127.0.0.1:8000/api/docs to explore and try the API in **Swagger UI**. Nothing
becomes reachable over HTTP unless you mark it ``@remote``.

Business rules
--------------

``raise FieldError("message", "Links are not allowed")`` rejects input for a reason a type
can't express. The message appears under the field, exactly like validation errors, and the
API answers ``422`` with the same details.

The complete file
-----------------

.. literalinclude:: steps/step5.py
   :caption: guestbook.py

Next: :doc:`06-project-structure`.

6. Growing into a project
=========================

One file was perfect to learn with. Real applications deserve a structure where each module has
one job. Here is the same guestbook as a project:

.. code-block:: text

   guestbook/
   ├── app.py               # the composition root: builds the app from its parts
   ├── settings.py          # settings from the environment
   ├── models/
   │   ├── database.py      # the engine and the declarative base
   │   └── entry.py         # the table, and the shapes that cross the API and forms
   ├── services/
   │   └── guestbook.py     # business logic (+ the JSON API)
   ├── views/
   │   ├── styles/          # the theme and shared styles
   │   ├── components/
   │   │   └── entry_card.py
   │   └── pages/
   │       └── home.py      # the page, declared on a Router
   └── tests/
       ├── conftest.py
       └── test_guestbook.py

Pages on a router
-----------------

A module can't use ``@app.page`` without importing the app, and the app imports the pages:
that's a circular import. A :class:`~rational.Router` records pages instead, and the app
includes it:

.. literalinclude:: guestbook/views/pages/home.py
   :pyobject: Home

The composition root
--------------------

``app.py`` is the only place that knows how the pieces fit together:

.. literalinclude:: guestbook/app.py
   :caption: app.py

Settings
--------

Configuration comes from the environment, with safe defaults for development:

.. literalinclude:: guestbook/settings.py
   :caption: settings.py

The other modules
-----------------

.. literalinclude:: guestbook/models/database.py
   :caption: models/database.py

.. literalinclude:: guestbook/models/entry.py
   :caption: models/entry.py

.. literalinclude:: guestbook/services/guestbook.py
   :caption: services/guestbook.py

Run it from the project folder, exactly as before:

.. code-block:: console

   $ cd guestbook
   $ python app.py --dev

Every example in the repository follows this layout; see :doc:`../examples/index`.

Next: :doc:`07-testing`.

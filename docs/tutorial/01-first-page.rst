1. Your first page
==================

Create ``guestbook.py``:

.. literalinclude:: steps/step1.py
   :caption: guestbook.py

Run it in development mode:

.. code-block:: console

   $ python guestbook.py --dev

Open http://127.0.0.1:8000. Leave the server running: from now on, every time you save the
file, the server restarts and the browser reloads by itself.

What happened
-------------

``App``
   The application. It is an ASGI app built on FastAPI, so any ASGI server can run it.

``@app.page("/")``
   Registers a :class:`~rational.Page` at a URL. One page instance exists per page view.

``render()``
   Returns what to show. ``Container``, ``Heading`` and ``Text`` are *primitives*: functions
   that build HTML elements with good default styles.

``app.run()``
   Reads the command line: ``--dev`` for development, ``--prod`` for production.

Look at the page source in your browser. It is plain HTML and CSS. Because this page has no
event handlers, Rational doesn't send any JavaScript at all.

Next: :doc:`02-components`.

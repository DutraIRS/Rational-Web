Quickstart
==========

Installation
------------

Rational Web needs Python 3.11 or newer.

.. code-block:: console

   $ python -m pip install rational            # core
   $ python -m pip install "rational[db]"      # + SQLAlchemy / aiosqlite

Want a ready-made project layout instead of a single file? ``rational new mysite`` creates
``mysite/`` with an app, a page, a test and a README, and ``cd mysite && python app.py --dev`` runs it.

Your first app
--------------

Create ``app.py``:

.. code-block:: python

   from rational import App, Button, Card, Container, Heading, Input, Page, State, Text

   app = App(title="Hello")


   @app.page("/")
   class Home(Page):
       name = State("")

       def set_name(self, value: str):
           self.name = value

       def render(self):
           return Container(
               Card(
                   Heading("Hello", level=1),
                   Input("Your name", on_input=self.set_name),
                   Text(f"Nice to meet you, {self.name or 'stranger'}."),
               ),
               max_width=560,
           )


   if __name__ == "__main__":
       app.run()

Run it in development mode:

.. code-block:: console

   $ python app.py --dev

Open http://127.0.0.1:8000. Edit the file and save: the server restarts and the
browser reloads by itself. Errors show the failing line of *your* code with a hint.

What just happened
------------------

1. ``GET /`` created a ``Home`` page, rendered it to HTML on the server and compiled
   only the CSS it uses.
2. Because the page has an event handler, the response also carries a small manifest
   and ``runtime.js`` (≈8 KiB gzipped). Static pages get neither.
3. Typing sends the (debounced) value to ``set_name`` over HTTP. The value is
   validated against the ``str`` annotation, ``name`` changes, and only the components
   that read ``name`` are re-rendered and patched into the page.

Next steps
----------

* :doc:`components` — props, state, identity and events.
* :doc:`styling` — ``Style``, themes and responsive design.
* :doc:`services` — server operations, the JSON API and databases.
* :doc:`running` — development, production and deployment options.
* The ``examples/`` directory: ``hello``, ``counter``, ``todos`` (multi-user CRUD) and
  ``dashboard`` (responsive, no custom CSS).

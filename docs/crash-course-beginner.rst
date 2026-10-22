Crash course: Python developer, new to the web
==============================================

You can write Python; you have never built a web page. This page teaches the four web concepts
you need, shows how Rational Web expresses each one in Python, and ends with a working app you
wrote while reading. Nothing here requires knowing HTML, CSS or JavaScript first.

What actually happens when someone visits your site
----------------------------------------------------

1. Their browser asks your **server** for an address, like ``GET /profile``.
2. Your server runs *your Python code* and produces a **page**: HTML, the text-and-structure
   format browsers render.
3. The browser draws it. If the page needs to react to clicks, a very small script (Rational
   Web ships it for you) tells your server "the user clicked this", and your Python runs again.

That's the loop: browser asks, Python answers. Everything below is a variation on it.

Concept 1 — Pages: code that answers an address
-----------------------------------------------

.. code-block:: python

   from rational import App, Heading, Page, Text

   app = App(title="My site")


   @app.page("/")
   class Home(Page):
       def render(self):
           return Heading("Hello, world", level=1)


   @app.page("/user/{name}")          # /user/ada, /user/grace, ...
   class Profile(Page):
       name: str                       # validated from the URL

       def render(self):
           return Heading(f"Hello, {self.name}", level=1)

   if __name__ == "__main__":
       app.run()                       # run: python app.py --dev

``render()`` returns the page's content as Python objects — ``Heading``, ``Text``, ``Button``.
The framework turns them into HTML. There is one object per HTML building block; you learn them
as you need them, and ``View page source`` in the browser always shows you what your objects
became.

Concept 2 — Interactivity: Python functions called by clicks
------------------------------------------------------------

A page that just displays is done: it ships zero JavaScript. To react to the user, connect an
event handler — a normal method, but it runs on your server when the user acts:

.. code-block:: python

   from rational import Button, Column, Page, State, Text


   @app.page("/")
   class Counter(Page):
       count = State(0)                # "remember this between clicks"

       def increment(self):
           self.count += 1

       def render(self):
           return Column(
               Text(f"Count: {self.count}"),
               Button("Add one", on_click=self.increment),
           )

``State`` is the memory of the page. When a handler changes it, the parts of the page that used
it are re-rendered on the server and updated in the browser — focus and typing are preserved.
You never write the update step; assigning to ``State`` is the whole job.

Forms work the same way, and their input is checked before your code sees it:

.. code-block:: python

   from pydantic import BaseModel, Field


   class JoinForm(BaseModel):
       name: str = Field(min_length=1, max_length=40)


   # inside a page:
   #     Form(Input("Your name", name="name"), Button("Join", type="submit"),
   #          on_submit=self.join)
   async def join(self, form: JoinForm):
       ...   # form.name is a valid, trimmed string — or the user saw a message already

Concept 3 — Remembering things: the database
---------------------------------------------

Visitors come back; pages forget. Data you keep between requests lives in a database — you talk
to it with SQLAlchemy, and Rational Web wraps the async parts:

.. code-block:: python

   # models/database.py — one engine for the whole app
   from rational.backend import Database

   database = Database("sqlite+aiosqlite:///app.db")


   # models/entry.py — a table is a class; a row is an instance
   class Entry(database.Base):
       id: Mapped[int] = mapped_column(primary_key=True)
       text: Mapped[str] = mapped_column(String(280))

Then a **service** — your rules, in one place — reads and writes it:

.. code-block:: python

   from rational.backend import Service, remote


   class GuestbookService(Service):
       @remote(method="GET")
       async def entries(self) -> list[Entry]:
           """Every entry, newest first."""
           ...

Pages call services through ``self.use(GuestbookService)``; loading data belongs in
``async def mount(self)``, which runs before the first render:

.. code-block:: python

   class Home(Page):
       entries = State(factory=list)

       async def mount(self):
           self.entries = await self.use(GuestbookService).entries()

Concept 4 — Making it look right: styles
----------------------------------------

CSS (the web's styling language) is expressed here as ``Style`` values — Python objects,
composed with ``|``:

.. code-block:: python

   from rational import Style

   CARD = Style(padding="md", shadow="lg") | Style(border_left="4px solid var(--rw-color-primary)")

   Card(..., style=CARD)

Named sizes (``"md"``, ``"lg"``), theme colours, ``viewport={"narrow": ...}`` for phones — the
framework compiles clean CSS from it and reuses what it has already emitted. Start with the
default theme; restyle later by changing values, not by learning a stylesheet language first.

Your first app, in one file
---------------------------

.. code-block:: python

   # app.py — run with: python app.py --dev
   from rational import App, Button, Card, Column, Heading, Input, Page, State, Text

   app = App(title="Notes")


   @app.page("/")
   class Home(Page):
       notes = State(factory=list)

       def add(self, value: str):          # wired to the input; runs on the server
           self.notes = [*self.notes, value]

       def render(self):
           return Column(
               Heading("My notes", level=1),
               Card(
                   Input("New note", on_input=lambda v: None),   # display only, see below
                   Button("Add", on_click=lambda: self.add("first note")),
               ),
               *[Text(n) for n in self.notes],
               max_width=560,
           )


   if __name__ == "__main__":
       app.run()

Save it, run ``python app.py --dev``, open http://127.0.0.1:8000. Edit the file: the server
restarts and the browser reloads by itself; errors are shown with the failing line of your code
and a hint. When it works, replace the input-and-button with the ``Form`` pattern above to get
validation, then follow the tutorial to add the database.

Words you'll meet
-----------------

``HTML``
   The text format pages are written in; you produce it through Python objects.
``route``
   An address (``/``, ``/user/ada``) and the code that answers it.
``request / response``
   One browser question and your server's answer.
``session``
   The server's memory of one visitor ("who is signed in"), keyed by a cookie the browser
   returns automatically. Rational Web creates and protects it for you.
``API``
   Your service methods, callable as JSON over HTTP — free, documented at ``/api/docs``.
``CSS``
   The language of visual style; here, values you pass as ``style=``.

Where to go next
----------------

* :doc:`tutorial/index` — the guestbook, step by step, from this file to a real project.
* :doc:`components` and :doc:`styling` — the full component and style catalogs.
* :doc:`examples/index` — ten complete applications, explained file by file. ``counter`` and
  ``todos`` are the natural second and third things to read.
* :doc:`security` — what the framework already protects you from, and what's left to you.

Client components
=================

A normal component runs on the server: each click is a small request, and the server answers with
the changed HTML. That keeps logic, data and secrets in one place, and it is the right default.

A **client component** runs in the browser. Its Python code is compiled to JavaScript, so its event
handlers run on the spot, with no request at all. Use one for interactions that must feel instant or
work offline once loaded: toggles, tabs, sliders, filters over data already on the page, live form
feedback, a counter. When it needs data, it calls a service.

.. code-block:: python

   from rational import Button, ClientComponent, Row, State, Text


   class Counter(ClientComponent):
       start: int = 0
       count = State(0)

       def mount(self):
           self.count = self.start

       def increment(self):
           self.count += 1

       def render(self):
           return Row(Text(f"Count: {self.count}"), Button("+1", on_click=self.increment))

Use it anywhere, like any component: ``Counter(start=5)``.

How it works
------------

1. **The server renders it first.** The page arrives with real HTML: it shows, and search engines
   see it, before any script runs. The server also sends the component's props and state.
2. **The compiler translates it once.** The first time the component renders, its methods are compiled
   to a small JavaScript module, cached and served with long-lived caching.
3. **The browser takes over** ("hydrates" it): it loads the module, attaches the handlers and from then
   on re-renders the component itself whenever its state changes.

The same Python code produces both renders, and the browser's render is checked against the
server's in the test suite, value by value. When the server later re-renders the component that
*contains* a client component (because of a server event), the client component receives its new
props and keeps its own state.

What the code can do
--------------------

Props
   Annotated class attributes, as for every component. Their values must be JSON data. A prop can
   also be a function when a client component creates another one in the browser (a callback):
   ``Item(title=t, on_remove=self.remove)``. Props are read-only; copy one into a ``State`` to change it.

State
   ``State(default)`` or ``State(factory=...)`` with JSON data, component scope only (``page`` and
   ``session`` scopes live on the server). Assign to update: ``self.items = [*self.items, item]``.
   Changing a list or dict in place is picked up when the handler returns.

Events
   ``on_click=self.method``, a ``lambda`` (``lambda item=item: self.remove(item)``) or ``js.*``
   operations, alone or in a list. As on the server, ``on_input`` and ``on_change`` handlers receive
   the value, ``on_submit`` the form's fields as a dict, and a parameter annotated ``int``, ``float``,
   ``bool`` or ``str`` is converted.

Lifecycle
   ``mount()`` runs where the instance is created: on the server for the first render, in the browser
   for instances that another client component creates later. ``hydrated()`` runs in the browser
   once the instance is interactive. Either may be ``async``.

Services
   ``await self.remote(Service.method, name=value)`` calls a ``@remote`` method and returns its JSON
   result. In the browser it is an HTTP request with the session's CSRF token; during the server's
   first render it calls the method directly. Failures arrive as :class:`~rational.RemoteError`::

      async def save(self):
          try:
              saved = await self.remote(Notes.add, text=self.draft)
          except RemoteError as e:
              self.error = e.message
              return
          self.notes = [*self.notes, saved]

Children
   ``self.children`` renders whatever the parent passed in. Server components passed in by a server
   parent stay server components, with their own server events, inside the client component.

Navigation and helpers
   ``self.navigate("/path")``, ``self.run_js(js.focus("#id"))``, ``self.touch()``, and
   ``await asyncio.sleep(seconds)`` (it stops when the component leaves the page).

Styles
   ``style=`` takes a constant ``Style``, or a choice between constants:
   ``style=ACTIVE if self.on else None``. Every choice is compiled up front, so the browser never
   needs the server to style a new state.

The Python you can use
----------------------

Inside methods: assignments (including ``+=``, tuple unpacking, items and slices to read), ``if``,
``for``, ``while``, ``break``, ``continue``, ``try``/``except``/``finally``, ``raise``, ``assert``,
``del`` of items, ``return``, comprehensions, lambdas, f-strings with format specs, ``await``, and the
operators with Python's meaning: ``//`` and ``%`` round like Python, ``==`` compares lists and dicts by
value, an empty list is false, ``-1`` indexes from the end.

Built-ins: ``len``, ``str``, ``repr``, ``int``, ``float``, ``bool``, ``abs``, ``round``, ``min``,
``max``, ``sum``, ``range``, ``enumerate``, ``zip``, ``sorted``, ``reversed``, ``list``, ``tuple``,
``dict``, ``any``, ``all``, ``isinstance``, ``chr``, ``ord`` and ``print``. The common methods of
``str``, ``list`` and ``dict``, plus ``asyncio.sleep``, ``math.floor``/``ceil``/``sqrt``,
``time.time`` and ``random.random``/``randint``/``choice``. Module-level functions that you call are
compiled too; module-level constants are inlined.

Anything else is a compile error that names the file, the line and the reason, for example::

   rational.client.compiler.ClientCompileError: self.context is only available on the server, not in client code
     File "app/views/components/cart.py", line 31, in Cart.render
       return Text(self.context.user)

Differences from Python
~~~~~~~~~~~~~~~~~~~~~~~

JavaScript has one number type, so a few things cannot match exactly. They are deliberate and small:

* A float with no fractional part prints like an integer: ``f"{8 / 2}"`` shows ``4`` in the browser
  and ``4.0`` on the server. Give floats a format (``f"{price:.2f}"``, ``f"{ratio:g}"``) and both agree.
* Tuples become lists, so ``repr((1, 2))`` shows ``[1, 2]``.
* Dictionary keys are strings, as in JSON.
* ``isinstance(x, float)`` is false for whole numbers.

What stays on the server
------------------------

A client component cannot use ``self.context``, the session, the database or server components
(other than as children it is given). Everything private stays behind ``@remote`` services, which
check sign-in (``auth="required"``) and validate their inputs exactly as for any other caller.

Security
--------

The browser builds elements with DOM methods, never by parsing strings: text is text. Tag names,
attribute names and event wiring are fixed at compile time; a URL attribute built from data
(``href=f"/items/{id}"``) is checked in the browser, and ``javascript:`` URLs are refused.
``unsafe_html()`` accepts constant markup only. Calls to services carry the session's CSRF token.

Deploying
---------

Nothing to build: the modules are compiled when the app first renders them. A page that only has
client components needs no server session, and ``python app.py --export site/`` exports it with its
scripts. On a static host, calls to ``@remote`` services need the API to be served somewhere.

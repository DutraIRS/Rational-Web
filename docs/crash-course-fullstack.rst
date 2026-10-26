Crash course: coming from React, Vue or Django
==============================================

You already know how the web works: requests, components, state, an API, a database. This page
maps what you know onto Rational Web, and calls out the three ideas that are genuinely
different. Reading it takes ten minutes; the code you write is real and runs as printed.

Install and run
---------------

.. code-block:: console

   $ python -m pip install "rational[db]"
   $ python app.py --dev     # hot reload, live browser reload, readable error pages

There is no build step, no ``package.json``, no bundler, no CORS. Pages are served at ``/``,
your JSON API at ``/api`` (interactive docs at ``/api/docs``), framework assets at
``/_rational`` — one origin, one process.

The mental model in three sentences
-----------------------------------

1. **Your components are server-side Python objects.** Their ``render()`` produces HTML on the
   server, and ``State`` attributes are reactivity roots: writing one marks the components that
   read it dirty, and the server sends back just their HTML.
2. **The browser is a thin delivery mechanism.** An ~8 KiB runtime wires events to the server,
   applies the HTML patches (preserving focus and caret), and runs the small closed set of
   ``js.*`` operations locally. There is no client-side component tree, no hydration, no virtual
   DOM, and no client router.
3. **The network boundary is explicit.** Every event handler is a server round trip you can see
   in the network tab. Only methods marked ``@remote`` are addressable as HTTP; nothing else is
   callable from the browser, by accident or otherwise.

Translation table
-----------------

===================================  =====================================================
What you know                        What Rational Web does
===================================  =====================================================
``<Component>`` + JSX/templating     ``class Thing(Component)`` returning Python objects
props                                annotated class attributes (``name: str = "Ada"``)
``useState``                         ``count = State(0)`` (also page and session scopes)
``useEffect`` / fetch-on-mount       ``async def mount(self)`` — runs on the server
``onClick={fn}``                     ``Button("Go", on_click=self.go)``
controlled input                     ``Input(..., on_input=self.set_x)`` (debounced server-side)
re-render + diff/hydration           server re-render of dirty components + DOM morph patch
context / store (Redux, Pinia)       ``State(scope="session")`` — server-side, per visitor
CSS-in-JS / Tailwind classes         ``Style(...)`` values compiled to hashed CSS classes
``react-router`` / vue-router        ``@app.page("/posts/{slug}")`` — routing is on the server
``fetch("/api/x")`` from the client   ``self.use(MyService).x()`` — a typed Python call
Express/FastAPI/Laravel controllers   ``Service`` classes with ``@remote`` methods
ORM models                           SQLAlchemy 2.0 async models (no second query language)
===================================  =====================================================

A component, for orientation
----------------------------

.. code-block:: python

   from rational import Button, Card, Component, State, Text


   class Tagger(Component):
       tags = State(factory=list)

       def add(self, value: str):
           self.tags = [*self.tags, value]   # plain Python: assign a new value

       def render(self):
           return Card(
               Text(" ".join(f"#{t}" for t in self.tags) or "No tags yet"),
               Button("Add #python", on_click=lambda: self.add("python")),
           )

Clicking the button ``POST``\s to the server, ``add`` runs *on the server*, and the response
carries only the card's new HTML. It feels like client-side reactivity; the mechanism is a
round trip costing well under a millisecond of server time (see :doc:`benchmarks`).

Two rules that prevent most confusion:

* ``render()`` must not change state — do that in handlers or ``mount()``.
* Components in a list need ``key=`` so instances keep their state across re-renders — same
  idea as React keys, same failure mode when omitted.

Data: services instead of fetch calls
-------------------------------------

In a JS stack your component fetches an endpoint. Here, a **service** owns the rules and the
queries, and both pages and the JSON API call it:

.. code-block:: python

   from rational import FieldError
   from rational.backend import Service, remote


   class TodoService(Service):
       @remote(method="GET")
       async def list_todos(self) -> list[TodoOut]:
           """Every to-do for the current user."""
           ...

       @remote
       async def add(self, title: str) -> TodoOut:
           if not title.strip():
               raise FieldError("title", "Give it a name")   # shown under the field
           ...

The same method is two things at once: ``self.use(TodoService).add(title)`` from any component,
and a validated, documented ``POST /api/todo/add`` with an OpenAPI schema — the endpoint you'd
otherwise hand-write. ``FieldError`` places the message under the right form field, exactly
where a client-side validation library would.

Forms are validated from handler annotations (Pydantic): pass a form model as the handler's
parameter and invalid input never reaches your code.

Styling without a preprocessor
------------------------------

.. code-block:: python

   from rational import Style

   CARD = Style(padding="md", shadow="lg", viewport={"narrow": Style(shadow="none")})
   hero = Style(background="primary", color="on_primary") | Style(padding_y="xl")

``Style`` values are immutable and compose with ``|``. The compiler emits one hashed class per
element — no specificity wars, no unused CSS, no purge step. Themes (light/dark/system) are CSS
custom properties; ``viewport=`` is your media query and ``container=`` your container query.
Anything it can't express goes through the ``raw=`` escape hatch as plain CSS.

Escape hatches (use them without guilt)
---------------------------------------

* ``h("iframe", src=...)`` — any HTML element.
* ``Style(raw={...})`` — any CSS.
* A FastAPI ``APIRouter`` mounted as-is — the blog example serves RSS this way.
* Hand-written JavaScript if you truly need it; pages without handlers ship zero JS.

What to read next
-----------------

* :doc:`components` — props, state scopes, identity, the event system, ``js.*`` operations.
* :doc:`services` — services, ``@remote``, databases, transactions.
* :doc:`projects` — the ``app.py`` / ``settings.py`` / ``models`` / ``services`` / ``views``
  layout every example uses.
* :doc:`examples/index` — the ``todos`` and ``social-network`` walkthroughs read well for a
  second pass; ``marketplace`` shows sessions and transactions.
* :doc:`design` — the full decision record (updates, transport, identity) if you want the why.

Everything a Vue app does, and how it is done here
--------------------------------------------------

The capabilities are the same; the shape is Python's: classes, decorators and typed values instead of
templates and options objects.

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Capability (Vue)
     - Rational Web
   * - Reactive state (``ref``, ``reactive``)
     - ``State(...)`` attributes; per component, page or session.
   * - Derived state (``computed``)
     - ``@computed`` methods, cached until their state changes.
   * - Reactions (``watch``)
     - ``@watch("name")`` methods, batched, sync or async.
   * - Props and events up (``emit``)
     - Annotated props; pass a method as a prop (``on_select=self.select``) to call the parent.
   * - Slots
     - ``self.children``.
   * - Two-way binding (``v-model``)
     - ``bind=self.bind("name")`` on ``Input``, ``Textarea``, ``Select``, ``Checkbox``.
   * - ``provide`` / ``inject``
     - ``self.provide(key, value)`` / ``self.inject(key)``.
   * - Lifecycle hooks
     - ``mount()``, ``unmount()``; ``hydrated()`` in client components.
   * - ``v-if``, ``v-for``, ``key``
     - Python ``if`` and comprehensions; ``key=`` on elements and components.
   * - Single-file components, scoped CSS
     - Component classes; ``Style`` values compile to hashed classes.
   * - Client-side rendering
     - :doc:`client-components`: Python compiled to JavaScript, rendered by the server first.
   * - SSR and hydration
     - The default: every page is server-rendered HTML; client components hydrate.
   * - Router, guards, navigation
     - ``@app.page("/path/{id}")``, ``auth="required"``, ``Redirect``, ``self.navigate()``,
       ``App(client_nav=True)`` for in-place navigation.
   * - ``Transition``
     - CSS transitions in ``Style``; ``App(view_transitions=True)`` animates page changes.
   * - ``Teleport``
     - ``Modal`` uses the native ``<dialog>`` top layer; menus and toasts are positioned by CSS.
   * - ``Suspense``, async components
     - ``Suspense``; ``async def mount()`` and ``async def render()``.
   * - Store (Pinia)
     - ``State(scope="page")`` / ``State(scope="session")``, services for shared data,
       live session sync across tabs and workers.
   * - Custom directives
     - ``js.*`` browser operations, or a client component.
   * - TypeScript
     - Type hints, checked by mypy; payloads and API bodies validated at runtime.
   * - Devtools
     - Readable error pages and overlays in ``--dev``; ``rational.testing`` for inspection. There is
       no component inspector extension.
   * - Hot module replacement
     - ``--dev`` restarts the app and reloads the page on save; component state is not preserved.
   * - ``KeepAlive``
     - Not needed for most uses: keep state that must outlive a component in page or session scope.

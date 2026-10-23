Design
======

This page records how the v0.1 specification (``ideas/``) was matured into an
implementation: the open questions it left, and the decisions taken.

Principles
----------

* Composition over inheritance for styles and reusable behaviour.
* Explicit remote exposure: Python methods are never callable from browsers by accident.
* Predictable execution: it is always clear whether code runs on the server or in the browser.
* Immutable style values and render nodes; state is explicitly mutable.
* Secure by default; progressive enhancement; a small stable core with inspectable output.

Non-goals for 0.x: a Python-to-JavaScript compiler, a React replacement, automatic
distributed state, reimplementing SQLAlchemy, Bootstrap/Tailwind parity.

Decisions
---------

.. list-table::
   :header-rows: 1
   :widths: 20 80

   * - Area
     - Decision
   * - Rendering
     - Async render pass → immutable node IR → deterministic HTML serializer.
   * - Updates
     - The server re-renders each *dirty component*, diffs it against its previous tree and sends
       the smallest safe patch: text and attribute **edits** addressed by element path, or an HTML
       **morph** of the smallest differing subtree (keyed by ``data-rw-key``/``data-rw-c``/``id``),
       preserving focus and caret. A path that no longer matches makes the browser reload.
       ``App(fine_patches=False)`` always sends whole-component morphs.
   * - Transport
     - HTTP ``POST`` per event, one in flight per tab (client queue; input coalescing).
       WebSockets are deferred.
   * - Identity
     - ``parent/Class:n`` or ``parent/Class#key``. Same identity and class ⇒ the instance is
       reused (state kept, props refreshed). Unvisited instances are unmounted.
   * - DOM boundary
     - A single-root render carries ``data-rw-c``; otherwise a ``<div>`` wrapper is emitted.
   * - State
     - ``State(default | factory, scope=component|page|session)``; reads during render are
       tracked; changed writes mark readers dirty; outermost dirty components re-render
       first. In-place mutation needs ``touch()``.
   * - Handlers
     - Registered at render time under opaque ids ``<component>.<n>``, stable across
       re-renders so double clicks are not lost. Payloads validated from annotations.
   * - Manifest
     - JSON in ``<script type="application/json">``; event wiring lives in ``data-rw-on-*``
       attributes. Pages without handlers ship no manifest, no runtime and no session.
   * - Local operations
     - A closed ``js.*`` set (classes, attributes, focus, theme), never compiled Python.
   * - Sessions
     - Opaque cookie id → server data; rotation on login/logout; in-memory stores behind
       the ``SessionBackend`` protocol.
   * - Remote API
     - ``@remote`` → FastAPI route under ``/api`` with a generated body model, response
       model and OpenAPI entry; CSRF for cookie sessions; safe structured errors.
   * - Database
     - Plain SQLAlchemy 2.0 async engine and sessions; no second query language.
   * - Styles
     - snake_case properties, px for numbers, scale and colour tokens, validated values,
       ``raw=`` escape hatch. One hashed class per element; precedence is
       theme < component default < variant < user ``style=``.
   * - Responsive
     - Named viewport breakpoints (``@media``) and container sizes (``@container``).
   * - Themes
     - Semantic tokens as CSS custom properties; four presets; light/dark/system.
   * - Running
     - ``--dev`` (supervised hot reload, live reload, readable errors) and ``--prod``
       (one origin: pages ``/``, API ``/api``, assets ``/_rational``).

The event protocol (v1)
-----------------------

Request (``POST /_rational/event``, header ``X-RW-CSRF``, session cookie)::

   {"v": 1, "page": "<page view id>", "rev": 3, "handler": "c1.1", "payload": {"value": "Ada"}}

Response::

   {"v": 1, "rev": 4,
    "patches": [{"op": "morph", "id": "c1", "html": "<div data-rw-c=\"c1\">…</div>"}],
    "css": [".rw-1a2b3c4d{…}"],
    "actions": [{"op": "navigate", "url": "/done"}],
    "error": {"code": "validation_error", "message": "…", "details": [{"field": "age", "message": "…"}]}}

``410`` means the page view expired (the runtime reloads); ``403`` a session or CSRF
mismatch; ``429`` the rate limit. An unknown handler answers with ``error.code ==
"stale"`` plus a full re-render, so the page resynchronizes instead of breaking.

Known limitations
-----------------

* Server-held page state requires one process or sticky sessions.
* Unkeyed siblings of the same class in conditional branches can swap state: use ``key=``.
* ``js.*`` changes survive a server re-render unless the server changes that same attribute or
  replaces the element (with ``fine_patches=False`` they are reset).
* Mounted sub-applications do not receive lifespan events, so ``on_startup`` hooks of a
  mounted ``App`` must be called by the host application.

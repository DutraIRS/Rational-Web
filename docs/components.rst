Components, state and events
============================

Pages and components
--------------------

A :class:`~rational.Component` renders a subtree; a :class:`~rational.Page` is a
component registered at a URL. ``render()`` returns primitives (``Text``, ``Button``,
``Row`` …), other components, strings, lists, or ``None``.

.. code-block:: python

   class Greeting(Component):
       name: str                 # a required prop
       excited: bool = False     # an optional prop

       def render(self):
           return Text(f"Hello, {self.name}{'!' if self.excited else '.'}")

   Greeting(name="Ada", excited=True)

* Annotated class attributes are **props**: constructor keywords, checked for missing or
  unknown names. Their values are not validated at runtime; annotations support static typing.
* Positional arguments become ``self.children``.
* ``key=`` gives a stable identity among siblings; ``style=`` merges into the root element.

Path parameters are props too, validated against their annotation:

.. code-block:: python

   @app.page("/users/{user_id}")
   class UserPage(Page):
       user_id: int          # "/users/abc" -> 404

Lifecycle
---------

``mount()``
    Called once before the first render of an instance; may be ``async``. Load data here.
``render()``
    Called on every (re)render; may be ``async``. Must not change state.
``unmount()``
    Called when the instance leaves the tree.

One ``Page`` instance exists per page view. Its components live on the server until
the view expires (30 minutes idle by default).

State
-----

.. code-block:: python

   class Counter(Component):
       count = State(0)                       # per instance
       items = State(factory=list)            # fresh list per instance
       theme = State("light", scope="page")   # shared by instances on one page view
       cart = State(0, scope="session")       # shared across the browser session's tabs

Reading a ``State`` during ``render()`` records a dependency. Assigning a *different*
value marks every dependent component for re-render after the event. In-place mutation
is not detected: reassign (``self.items = [*self.items, x]``) or call
``self.touch("items")``.

Identity
--------

A component's identity is its position: ``parent/ClassName:index``, or
``parent/ClassName#key`` with ``key=``. When the parent re-renders, an instance with the
same identity and class is **reused** — its state survives and its props are refreshed.
Always pass ``key=`` for items in lists or conditional branches, as you would in React.

Events
------

Pass a callable as ``on_click``, ``on_input``, ``on_change``, ``on_submit``,
``on_keydown``, ``on_enter`` or ``on_blur``. Handlers run **on the server**, may be
``async``, and take zero or one argument whose annotation drives validation:

.. code-block:: python

   def increment(self): ...                     # no payload
   def set_age(self, value: int): ...           # input/change value, validated as int
   def save(self, form: SignupForm): ...        # submit: a Pydantic model
   def raw(self, event: Event): ...             # name, value, key, form

Invalid input never reaches the handler: the browser receives the errors and shows them
next to the matching fields (``aria-invalid`` + the field's error slot). For rules a type
can't express, raise ``FieldError("field", "message")`` from the handler or a service: the
message appears under that field in the same way.

Lambdas are fine and capture values **server-side** — the browser only ever sees an
opaque handler id::

   Button("Delete", on_click=lambda: self.delete(todo.id))

After a handler you can also call ``self.navigate("/path")`` or ``self.run_js(js.focus("#x"))``.

Browser-local operations
------------------------

For purely visual interactions there is a closed set of declarative operations that run
in the browser without a round trip::

   Button("Menu", on_click=js.toggle_class("open", target="#menu"))
   Button("Dark", on_click=js.set_theme("dark"))

Operations can be combined with a server handler. ``js.confirm()`` asks first and cancels
everything after it, including the server event, if the user declines::

   Button("Delete", on_click=[js.confirm("Delete this post?"), self.delete])

The full set, each taking an optional ``target`` selector (default: the element itself;
``closest:<selector>`` searches ancestors):

* classes and attributes: ``toggle_class``, ``add_class``, ``remove_class``, ``set_attr``, ``toggle_attr``
* visibility: ``show``, ``hide``, ``toggle`` (the ``hidden`` attribute) and ``remove``
* content: ``set_text``, ``set_value`` (fires ``input``), ``copy`` (clipboard), ``scroll_to``
* dialogs: ``open_dialog`` and ``close_dialog`` (a native ``<dialog>``, closing the nearest one by default)
* ``focus``, ``confirm``, ``set_theme``, ``toggle_theme``

They are not a Python-to-JavaScript compiler. A server re-render of the same element
resets classes it changed, so use them for state the server doesn't own.

Escape hatches
--------------

* ``h(tag, *children, **attrs)`` builds any element (``class_=``, ``aria_label=`` …).
* ``unsafe_html(markup)`` inserts trusted HTML verbatim.
* ``app.fastapi`` is the underlying FastAPI application for custom routes and middleware.

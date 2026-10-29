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

The HTML document around a page is set by attributes that are *not* props: ``title``,
``description``, ``lang`` (``<html lang>``, default: the request's locale), ``dir``
(``"rtl"`` for Arabic, Hebrew, Persian or Urdu), ``favicon`` (``False``: no icon link),
``head_start`` (trusted markup right after ``<meta charset>``, such as a CSP ``<meta>``) and
``head_end`` (trusted markup closing ``<head>``, after Rational's and the app's stylesheets, so a
page's own CSS wins). Set them on the class, or in ``mount()`` when they come from the page's
data, so one class can serve many pages:

.. code-block:: python

   @app.page("/{language}/docs/{slug}.html")
   class Doc(Page):
       language: str
       slug: str

       def mount(self):
           self.doc = load_doc(self.language, self.slug)
           self.title = self.doc.title
           self.lang = self.language
           self.dir = "rtl" if self.language == "ar" else None

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

Derived state, reactions and binding
------------------------------------

``@computed`` turns a method into a value read like an attribute. It is cached until state changes,
and whoever reads it re-renders when the state it was computed from changes::

    @computed
    def total(self) -> int:
        return sum(item.price for item in self.items)

``@watch("name", ...)`` runs a method after those ``State`` attributes change, before the page
re-renders. It receives ``(new, old)`` (or just ``new``, or nothing), may be async, and changes made
in one handler are batched into one call. Values set in ``mount()`` are the starting point, not changes::

    @watch("query")
    async def search(self, new: str) -> None:
        self.results = await self.use(SearchService).find(new)

``bind=self.bind("name")`` ties a form control to a ``State`` attribute both ways: the control shows
the value, and what the user enters is converted to the attribute's type (``int``, ``float``,
``bool``, ``str``) and stored. Input that is not valid yet is ignored. ``Input``, ``Textarea``,
``Select`` and ``Checkbox`` accept it::

    Input("Age", type="number", bind=self.bind("age"))

``self.provide(key, value)`` (in ``mount()`` or ``render()``) makes a value available to every
component inside this one, which read it with ``self.inject(key, default)``. To share changing data,
provide a component or an object with ``State``.

All of these work the same in :doc:`client components <client-components>`, except
``provide``/``inject`` (pass props there).

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

Forms from a model
------------------

``ModelForm(Model, on_submit=...)`` builds the whole form from a Pydantic model, so the fields,
labels, constraints and validation come from one place::

   class Signup(BaseModel):
       username: str = Field(min_length=3, max_length=20, description="Public name")
       email: str
       password: str = Field(min_length=8)
       age: int = Field(ge=18)
       newsletter: bool = False
       role: Role = Role.guest          # an Enum or Literal of strings becomes a select

   def join(self, data: Signup): ...    # validated before it runs
   ModelForm(Signup, on_submit=self.join, submit_label="Join")

``Field(title=, description=)`` set the label and help text; ``min_length``, ``max_length``, ``ge``
and ``le`` become HTML attributes (the server still validates). Names containing ``password`` or
``email`` get the right input type, and a password is never echoed back. Use
``json_schema_extra={"widget": "textarea"}`` (or ``"email"``, ``"url"``, ``"tel"``, ``"date"``…) to choose a
control. ``values=`` takes a dict or model instance to pre-fill an edit form, ``errors=`` shows
server-side messages, and ``exclude=`` drops fields. For anything custom, compose ``Form`` with
``Input``, ``Select`` and friends instead.

Browser-local operations
------------------------

For purely visual interactions there is a closed set of declarative operations that run
in the browser without a round trip::

   Button("Menu", on_click=js.toggle_class("open", target="#menu"))
   Button("Dark", on_click=js.set_theme("dark"))

Operations can be combined with a server handler. ``js.confirm()`` asks first and cancels
everything after it, including the server event, if the user declines::

   Button("Delete", on_click=[js.confirm("Delete this post?"), self.delete])

``js.optimistic(*ops)`` makes a change visible before the server answers. The operations run at
once; the server's patches then replace them (the server is always the source of truth). If the event
fails, or the network does, and the server did not re-render the enclosing component, that
component is restored to how it looked before::

   Button("Like", on_click=[js.optimistic(js.add_class("liked")), self.like])

The full set, each taking an optional ``target`` selector (default: the element itself;
``closest:<selector>`` searches ancestors):

* classes and attributes: ``toggle_class``, ``add_class``, ``remove_class``, ``set_attr``, ``toggle_attr``
* visibility: ``show``, ``hide``, ``toggle`` (the ``hidden`` attribute) and ``remove``
* content: ``set_text``, ``set_value`` (fires ``input``), ``copy`` (clipboard), ``scroll_to``
* dialogs: ``open_dialog`` and ``close_dialog`` (a native ``<dialog>``, closing the nearest one by default)
* ``focus``, ``confirm``, ``optimistic``, ``set_theme``, ``toggle_theme``

For logic that runs in the browser, write a :doc:`client component <client-components>`. The server
only patches what changed, so a client-side
change survives re-renders that don't touch the same attribute or text; if the server does change
it (or replaces the element), the server wins.

Dialogs, tabs, tables and toasts
--------------------------------

These run in the browser with no round trip, built on the operations above and on native
elements (``<dialog>``, ``role=tab``)::

   Button("Delete…", on_click=js.open_dialog("#confirm"))
   Modal(Text("Really?"), Button("Yes", on_click=self.delete), id="confirm", title="Delete")

   Tabs([("Profile", ProfileForm()), ("Billing", BillingForm())], id="settings")

   Table(["Name", "Role"], [["Ada", "Admin"], ["Linus", Badge("Guest")]], empty="No users")

   Toasts(Toast("Saved", tone="success"))

   Menu("Actions", MenuItem("Rename", on_click=self.rename), MenuItem("Docs", href="/docs"), id="actions")

``Menu`` and ``Tabs`` follow the WAI-ARIA patterns. Tabs use a roving ``tabindex`` and
Left/Right/Home/End. A menu opens with Enter, Space or the arrow keys, moves with
arrows/Home/End, and closes with Escape (focus returns to its button), Tab or an outside click.

``Modal`` gets focus trapping, a backdrop and Escape from the browser. ``Tabs`` renders every
panel and shows the selected one; a server re-render that changes the tabs resets the selection.
Toasts are dismissed in the browser; render them from state to show one on demand. ``id`` values
must be unique on the page and CSS-safe.

Escape hatches
--------------

* ``h(tag, *children, **attrs)`` builds any element (``class_=``, ``aria_label=`` …).
* ``unsafe_html(markup)`` inserts trusted HTML verbatim.
* ``app.fastapi`` is the underlying FastAPI application for custom routes and middleware.

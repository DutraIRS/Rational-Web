Styling and themes
==================

``Style``
---------

A :class:`~rational.Style` is an immutable, typed set of CSS declarations. ``None`` means
"unspecified" (never CSS ``none``). ``a | b`` merges right-biased; nested pseudo-state
and responsive styles merge recursively.

.. code-block:: python

   base = Style(color="on_primary", background="primary", padding=12, border_radius="md")
   button = base | Style(font_weight=600, hover=Style(background="primary_hover"))

Every element ends up with **one** generated class (``rw-<hash>``), so there are no
specificity battles; identical styles share a class across the page.

Values
------

* Numbers on length properties become pixels (``padding=12`` → ``12px``; ``0`` → ``0``).
* Scale tokens: spacing ``xs sm md lg xl 2xl 3xl``, radius ``none sm md lg xl full``,
  font sizes ``xs … 4xl``, shadows ``sm md lg``, fonts ``body heading mono``.
* Theme colour names (``primary``, ``on_surface``, ``muted`` …) become CSS variables, so
  light/dark switching needs no re-render.
* Shorthands: ``layout="vertical"|"horizontal"``, ``padding_x``/``padding_y``,
  ``margin_x``/``margin_y``, ``columns=3`` (equal grid tracks), ``border=True``,
  ``transition=True``.
* Anything else: ``raw={"text-underline-offset": "3px"}``.

Values containing ``; { } < >`` or ``/*`` are rejected when the ``Style`` is created, so
the error points at your line and CSS injection is impossible.

States and responsiveness
-------------------------

.. code-block:: python

   Style(
       padding=24,
       hover=Style(background="surface_alt"),     # wrapped in @media (hover: hover)
       focus_visible=Style(outline="2px solid"),
       disabled=Style(opacity=0.5),               # :disabled and [aria-disabled=true]
       viewport={"mobile": Style(padding=12)},    # @media
       container={"compact": Style(layout="vertical")},  # @container
   )

Viewport breakpoints (overridable with ``App(breakpoints=...)``):

===========  =====================
``mobile``   below 640px
``tablet``   640px – 1023px
``narrow``   below 1024px
``desktop``  1024px and up
``sm``       640px and up
``md``       768px and up
``lg``       1024px and up
``xl``       1280px and up
===========  =====================

Container sizes: ``compact`` (below 480px), ``regular`` (480px and up), ``wide``
(900px and up). A container must establish itself with
``Style(container_type="inline-size")``.

Python never inspects the viewport: the browser evaluates the generated queries.

Themes
------

``App(theme=...)`` takes a preset — ``modern``, ``minimal``, ``soft``,
``professional`` — or a :class:`~rational.Theme`. ``theme_mode`` is ``"system"``
(follows the OS), ``"light"`` or ``"dark"``. Customize a preset::

   brand = MODERN.with_colors(light={"primary": "#ff0066"}, dark={"primary": "#ff5c9a"})
   app = App(theme=brand)

Every theme includes a reset, a visible ``:focus-visible`` ring and
``prefers-reduced-motion`` support.

Layout primitives
-----------------

``Stack``, ``Row`` and ``Column`` wrap flexbox; ``Row(collapse="mobile")`` stacks
vertically below a breakpoint. ``Grid(min_column_width=240)`` fits as many columns as the
space allows without media queries; ``Grid(columns=3)`` collapses to one column on
mobile. ``Card``, ``Container``, ``Spacer``, ``Divider`` and the semantic ``Header``,
``Main``, ``Footer``, ``Nav``, ``Section``, ``Article``, ``Aside`` complete the set.

``Badge("new", tone="success")`` labels statuses, tags and counts (tones: ``neutral``,
``primary``, ``success``, ``warning``, ``danger``). ``Avatar("Ada Lovelace")`` shows a picture,
or the person's initials when there is no ``src``.

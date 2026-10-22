4. Styling and responsive layout
================================

.. literalinclude:: steps/step4.py
   :caption: guestbook.py

Themes
------

``App(theme="soft")`` picks a preset: ``modern``, ``minimal``, ``soft`` or
``professional``. Themes define colours, spacing, radius, fonts and shadows as CSS variables,
with light and dark variants. ``js.toggle_theme()`` switches between them **in the browser**,
with no server round trip, and remembers the choice in a cookie.

Styles are values
-----------------

``Style(...)`` objects are immutable, so define them once and reuse them. ``a | b`` merges two
styles, with ``b`` winning. Values can be theme tokens (``"primary"``, ``"lg"``), numbers
(pixels) or any CSS value. Pseudo-states such as ``hover=Style(...)`` nest naturally.

Each element gets exactly one generated class, and identical styles share it. You never fight
CSS specificity.

Responsive without media queries…
----------------------------------

``Grid(min_column_width=240)`` places as many columns as fit, each at least 240px wide. It
adapts to any screen without a single breakpoint.

…and with them when you need them
---------------------------------

``Row(collapse="mobile")`` puts the form beside the messages on wider screens and stacks them
on phones. ``viewport={"mobile": Style(width="100%")}`` changes a style below 640px. The names
(``mobile``, ``tablet``, ``narrow``, ``desktop``, ``sm`` … ``xl``) are listed in :doc:`../styling`.

Resize your browser window to watch the layout adapt.

Next: :doc:`05-data-and-api`.

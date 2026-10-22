2. Components and props
=======================

A page can be broken into reusable :class:`~rational.Component` classes. Let's show some
guestbook entries, each in its own card:

.. literalinclude:: steps/step2.py
   :caption: guestbook.py

Props
-----

Annotated class attributes are **props**, the inputs of a component. ``entry: Entry`` makes
``EntryCard(entry=...)`` required; a default value (``excited: bool = False``) makes a prop
optional. A misspelled or missing prop is an error when the component is created, not a
silent bug.

Keys
----

``key=`` gives each card a stable identity among its siblings. It doesn't matter yet, but
it will in the next step, once the cards have state of their own. When you render a list,
always pass a key.

Primitives you will use most
----------------------------

* Text: ``Heading``, ``Text``, ``Link``, ``Badge``
* Layout: ``Container``, ``Row``, ``Column``, ``Grid``, ``Card``
* Forms: ``Form``, ``Input``, ``Textarea``, ``Select``, ``Checkbox``, ``Button``

They are listed in the :doc:`../api`. For anything else, ``h("tag", ...)`` builds any element.

Next: :doc:`03-state-and-events`.

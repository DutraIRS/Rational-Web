3. State, events and forms
==========================

Visitors should be able to sign the guestbook and like messages:

.. literalinclude:: steps/step3.py
   :caption: guestbook.py

State
-----

``hearts = State(0)`` declares reactive state. Every ``EntryCard`` instance has its own
count. When ``like()`` assigns a new value, Rational re-renders the components that *read*
that state (here, just that card) and patches the page in place.

``entries = State(factory=list)`` gives each page view its own list. Use ``factory=`` for
mutable defaults, so instances never share a list.

Events
------

``on_click=self.like`` passes a method. It runs **on the server**: the browser only knows an
opaque handler id, never your method's name. Rational adds a ~4 KiB script to pages that have
handlers and wires everything up for you.

Forms and validation
--------------------

``on_submit=self.sign`` receives the form's fields. Because the parameter is annotated with
the Pydantic model ``SignForm``, the data is validated **before** your handler runs. Try
submitting an empty form: the errors appear under the right fields, and ``sign()`` is never
called with bad data.

``key=f"form-{len(self.entries)}"`` gives the form a new identity after each signature. A form
with a new key is a fresh form, so the fields are cleared.

Why the entries have ids
------------------------

New entries are inserted at the top, so positions shift. With ``key=e.id``, identity follows
the entry, not its position, and the card you liked keeps its hearts when others move.

Next: :doc:`04-styling`.

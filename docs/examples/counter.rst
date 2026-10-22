Counter
-------

The specification's counter, plus the interaction patterns you use every day.

.. code-block:: text

   counter/
   ├── app.py                    # composition root
   └── views/
       ├── components/           # counter.py (Counter), greeter.py (Greeter)
       ├── pages/                # home.py, on a Router
       └── styles/

1. A component with props and state
-----------------------------------

.. literalinclude:: ../../examples/counter/views/components/counter.py
   :pyobject: Counter

``label`` and ``step`` are props, set by whoever uses the component. ``count`` is state, owned
by each instance. ``disabled=self.count == 0`` shows that rendering is plain Python: the button
is disabled whenever the condition holds.

2. Typing, debounced
--------------------

.. literalinclude:: ../../examples/counter/views/components/greeter.py
   :pyobject: Greeter

``on_input`` waits until typing pauses (150 ms), then sends the value. The ``value: str``
annotation validates it before ``set_name`` runs.

3. The page
-----------

.. literalinclude:: ../../examples/counter/views/pages/home.py
   :caption: views/pages/home.py

The two counters have different ``key=`` values, so each keeps its own count.
``js.toggle_theme()`` runs in the browser: no request is sent.

4. The composition root
-----------------------

.. literalinclude:: ../../examples/counter/app.py
   :caption: app.py

Hello
=====

The smallest Rational Web app: one themed, server-rendered page.

.. literalinclude:: ../../examples/hello/app.py
   :caption: examples/hello/app.py

Things to notice:

* There are no event handlers, so the page ships **no JavaScript**: open the page source and
  look for ``<script>``, there is none.
* ``Container(..., tag="main")`` gives the page a ``<main>`` landmark for assistive technology.
* ``app.run()`` makes ``python app.py --dev`` and ``python app.py --prod`` work.

Run it:

.. code-block:: console

   $ python examples/hello/app.py --dev

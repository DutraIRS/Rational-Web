Dashboard
=========

A responsive analytics dashboard with zero hand-written CSS or JavaScript.

.. code-block:: text

   dashboard/
   ├── app.py               # composition root
   ├── models/              # metrics.py (the data)
   ├── services/            # metrics.py (MetricsService, also a JSON API)
   └── views/
       ├── components/      # sidebar, stat_card, region_chart, recent_orders
       ├── pages/           # overview.py
       └── styles/

1. Data first
-------------

.. literalinclude:: ../../examples/dashboard/services/metrics.py
   :pyobject: MetricsService

Components never fetch data themselves here: the page loads ``Metrics`` and passes plain values
down as props. That keeps components easy to reuse and to test.

2. A sidebar that moves
-----------------------

.. literalinclude:: ../../examples/dashboard/views/components/sidebar.py
   :pyobject: Sidebar

``viewport={"narrow": ...}`` changes the style below 1024px: the sidebar loses its full height
and its right border when it moves above the content.

3. A chart that measures itself
-------------------------------

.. literalinclude:: ../../examples/dashboard/views/components/region_chart.py
   :pyobject: RegionChart

``container_type="inline-size"`` makes the card a *container*; ``container={"compact": ...}``
hides the amounts when **the card** is narrow, whatever the size of the screen. That's what
makes a component reusable in any layout.

4. The page
-----------

.. literalinclude:: ../../examples/dashboard/views/pages/overview.py
   :pyobject: Overview

* ``Grid(min_column_width=200)`` fits as many KPI tiles per row as the space allows.
* ``Row(collapse="narrow")`` stacks the sidebar above the content on tablets and phones.
* ``set_range`` ignores values that aren't offered options: never trust the browser.

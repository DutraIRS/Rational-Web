Examples
========

Ten complete applications, from a single page to a social network. Every one is in the
repository's ``examples/`` folder, laid out like a real project, and covered by the test suite.

.. list-table::
   :header-rows: 1
   :widths: 22 48 30

   * - Example
     - What it is
     - What you'll learn
   * - :doc:`hello`
     - The smallest app: one static page
     - Pages, primitives, zero-JS output
   * - :doc:`counter`
     - The specification's counter
     - State, keys, events, debounced input
   * - :doc:`media`
     - Images, favicons, links, video and documents
     - Local assets, remote URLs, ``Image``, ``Link`` and the ``h()`` escape hatch
   * - :doc:`dashboard`
     - A responsive analytics dashboard
     - Breakpoints, container queries, fluid grids
   * - :doc:`cv-portfolio`
     - A one-page CV and portfolio
     - Content as data, function components, honeypot forms
   * - :doc:`todos`
     - Multi-user todo lists
     - Databases, services, per-user isolation, the JSON API
   * - :doc:`blog`
     - A blog with an editor
     - Path parameters, safe rich text, live preview, RSS
   * - :doc:`user-platform`
     - Accounts, roles and an admin area
     - Password hashing, authenticators, ``FieldError``, access control
   * - :doc:`marketplace`
     - A shop with a cart and checkout
     - Session state, transactions, money, overselling
   * - :doc:`social-network`
     - Posts, likes, follows and timelines
     - Relational queries without N+1, local updates

Suggested order: follow the table from top to bottom. Each example adds a few ideas to the
previous ones.

Running an example
------------------

.. code-block:: console

   $ pip install "rational[db]"
   $ cd examples/marketplace
   $ python app.py --dev

Database examples create their SQLite file next to ``app.py``; set ``DATABASE_URL`` to use another
database.

How every example is laid out
-----------------------------

.. code-block:: text

   example/
   ├── README.md          # what it shows and how to run it
   ├── app.py             # the composition root: App + routers + services + startup hooks
   ├── settings.py        # settings from the environment
   ├── models/            # database.py (engine + base), one file per table group
   ├── services/          # business rules (+ the JSON API)
   └── views/
       ├── styles/        # theme and shared styles
       ├── components/    # reusable components
       └── pages/         # pages, declared on Routers

``hello`` is the one exception: it stays a single file on purpose, to show the smallest possible app.

.. toctree::
   :hidden:

   hello
   counter
   media
   dashboard
   cv-portfolio
   todos
   blog
   user-platform
   marketplace
   social-network

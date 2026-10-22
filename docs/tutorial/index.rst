Tutorial: build a guestbook
===========================

In this tutorial you build a guestbook: a page where visitors leave messages. You start with a
single file and finish with a structured, tested project backed by a database, with a JSON
API and a production server.

Each step is a complete program you can run. The code shown here is the code in the
repository's ``docs/tutorial`` folder, and the test suite runs every step, so it is guaranteed
to work.

.. toctree::
   :maxdepth: 1

   01-first-page
   02-components
   03-state-and-events
   04-styling
   05-data-and-api
   06-project-structure
   07-testing
   08-deploying

You need Python 3.11 or newer:

.. code-block:: console

   $ python -m venv .venv
   $ source .venv/bin/activate        # Windows: .venv\Scripts\activate
   $ pip install "rational[db,testing]"

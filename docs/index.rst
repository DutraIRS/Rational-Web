Rational Web
============

*Trying to make web development less irrational.*

Rational Web is a Python-first, object-oriented web framework. Pages, components, services
and models are Python objects; HTML, CSS and JavaScript become implementation details behind
one consistent, typed, inspectable API. It is built on FastAPI, Pydantic and SQLAlchemy.

.. code-block:: python

   from rational import App, Button, Column, Component, Page, State, Text

   app = App()


   class Counter(Component):
       count = State(0)

       def increment(self):
           self.count += 1

       def render(self):
           return Column(Text(f"Count: {self.count}"), Button("Increment", on_click=self.increment))


   @app.page("/")
   class Home(Page):
       def render(self):
           return Counter()


   if __name__ == "__main__":
       app.run()   # python app.py --dev   |   python app.py --prod

* **Server-rendered first.** Every page is real HTML before any script runs. Static pages ship no
  JavaScript at all; interactive pages load a ~4 KiB runtime.
* **Explicit boundaries.** Event handlers run on the server; only ``@remote`` methods form an
  HTTP API, documented in Swagger UI. Nothing is callable from the browser by accident.
* **Typed boundaries.** Path parameters, event payloads and API bodies are validated from your
  annotations. Component prop annotations support static typing; runtime checks cover required
  and unexpected prop names.
* **Styles as values.** ``Style`` objects compile to hashed, deduplicated CSS with themes,
  breakpoints and container queries.
* **Secure by default.** Escaping, CSRF, session-bound events, validated payloads.

Where to start
--------------

Not sure where *you* should start?

* Coming from React, Vue or a Django-style stack: :doc:`crash-course-fullstack` maps what you
  know onto Rational Web in ten minutes.
* You know Python but are new to web development: :doc:`crash-course-beginner` teaches the four
  concepts you need, in Python terms.

:doc:`tutorial/index`
   Build a guestbook step by step, from one file to a tested, deployed project.
:doc:`examples/index`
   Ten complete applications, from a CV site to a marketplace, explained file by file.
:doc:`quickstart`
   The five-minute version.

.. toctree::
   :maxdepth: 2
   :caption: Learn

   quickstart
   crash-course-fullstack
   crash-course-beginner
   tutorial/index
   examples/index

.. toctree::
   :maxdepth: 2
   :caption: Guide

   components
   styling
   services
   projects
   running
   serverless
   concurrency
   i18n
   security
   testing

.. toctree::
   :maxdepth: 2
   :caption: Background

   design
   benchmarks

.. toctree::
   :maxdepth: 2
   :caption: Reference

   api

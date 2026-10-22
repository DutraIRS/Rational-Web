API reference
=============

Application
-----------

.. autoclass:: rational.App
   :members: page, service, include, url_for, on_startup, authenticate, static, run

.. autoclass:: rational.Router
   :members: page, service, on_startup, include

.. autoclass:: rational.Context
   :members:

Components
----------

.. autoclass:: rational.Component
   :members: render, mount, unmount, context, use, touch, navigate, run_js

.. autoclass:: rational.Page

.. autoclass:: rational.State

Primitives
----------

.. automodule:: rational.components.basic
   :members: Text, Heading, Button, ButtonLink, Link, Image, Badge, Avatar, button_style

.. automodule:: rational.components.layout
   :members: Stack, Row, Column, Grid, Card, Container, Spacer, Divider

.. automodule:: rational.components.forms
   :members: Form, Input, Textarea, Select, Checkbox

Events
------

.. automodule:: rational.events
   :members:

Styling
-------

.. autoclass:: rational.Style
   :members: items, key

.. autoclass:: rational.styling.style.StyleError

.. autoclass:: rational.Theme
   :members: with_colors, css

.. autoclass:: rational.Breakpoint

.. autoclass:: rational.styling.StyleCompiler
   :members: compile

Services and data
-----------------

.. autoclass:: rational.backend.Service
   :members:

.. autofunction:: rational.backend.remote

.. autoclass:: rational.backend.database.Database
   :members:

Sessions
--------

.. autoclass:: rational.session.Session
   :members: user, login, logout

.. autoclass:: rational.session.SessionBackend
   :members:

Errors
------

.. automodule:: rational.errors
   :members:

Rendering
---------

.. autofunction:: rational.h

.. autofunction:: rational.unsafe_html

Running
-------

.. automodule:: rational.cli
   :members: serve, main

Testing
-------

.. automodule:: rational.testing
   :members: TestClient, PageView

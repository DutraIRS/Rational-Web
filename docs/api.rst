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
   :members: render, mount, unmount, context, use, touch, navigate, run_js, run_task

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

.. automodule:: rational.components.modelform
   :members: ModelForm

.. automodule:: rational.components.overlay
   :members: Modal, Tabs, Table, Toast, Toasts, Menu, MenuItem

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

Client components
-----------------

.. autoclass:: rational.ClientComponent
   :members: remote, hydrated

.. autoexception:: rational.client.ClientCompileError

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

.. automodule:: rational.stores
   :members: PersistentSessionStore, RedisSessionDriver, MemorySessionDriver, SessionDriver

Security, cookies and sockets
-----------------------------

.. automodule:: rational.security
   :members: hash_password, verify_password, password_needs_rehash, Tokens, Signer, Box, InvalidToken

.. autoclass:: rational.cookies.Cookies
   :members: get, set, delete

.. autoclass:: rational.Socket
   :members: connect, receive, disconnect, send, join, leave, publish

.. autoclass:: rational.backend.database.Repository
   :members:

Jobs and email
--------------

.. automodule:: rational.jobs
   :members: Jobs, Job, JobStore, MemoryJobStore, RedisJobStore

.. automodule:: rational.mail
   :members: Mailer, Email, SMTP, Resend, Postmark, Console, Memory, html_to_text, render_email

.. automodule:: rational.accounts
   :members: Accounts

Errors and redirects
--------------------

.. automodule:: rational.errors
   :members:

.. autofunction:: rational.local_path

Concurrency
-----------

.. autofunction:: rational.timeout

.. autofunction:: rational.threaded

.. autoclass:: rational.HandlerTimeout

Rendering
---------

.. autofunction:: rational.h

.. autofunction:: rational.unsafe_html

Running
-------

.. automodule:: rational.cli
   :members: serve, main

.. automodule:: rational.scaffold
   :members: scaffold, ScaffoldError

.. automodule:: rational.export
   :members: export_site, ExportReport

Testing
-------

.. automodule:: rational.testing
   :members: TestClient, PageView

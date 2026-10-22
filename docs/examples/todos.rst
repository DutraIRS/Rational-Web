Todos
=====

A multi-user todo list: persistence, sign-in, a service that is also a REST API, and strict
per-user isolation.

.. code-block:: text

   todos/
   ├── app.py            # composition root
   ├── settings.py       # DATABASE_URL
   ├── models/           # database.py, todo.py (Todo, TodoOut, NewTodo), account.py (SignIn)
   ├── services/         # todos.py (TodoService)
   └── views/
       ├── components/   # todo_item.py (TodoItem)
       ├── pages/        # todos.py (Todos), login.py (Login)
       └── styles/

1. Settings and the database
----------------------------

.. literalinclude:: ../../examples/todos/settings.py
   :caption: settings.py

.. literalinclude:: ../../examples/todos/models/database.py
   :caption: models/database.py

2. The service owns the rules
-----------------------------

.. literalinclude:: ../../examples/todos/services/todos.py
   :caption: services/todos.py

Every query filters by ``self.user``. ``_owned`` answers "not found" for other users' todos,
so the API never even confirms they exist. Each ``@remote`` method becomes a typed endpoint:
``GET /api/todo/list-todos``, ``POST /api/todo/add`` and so on, all in Swagger UI at ``/api/docs``.

3. A component with a callback prop
-----------------------------------

.. literalinclude:: ../../examples/todos/views/components/todo_item.py
   :pyobject: TodoItem

``changed`` is a prop holding the page's ``reload`` method: the item tells its parent that
something changed. ``on_click=[js.confirm(...), self.remove]`` asks in the browser first; if the
user cancels, no request is sent.

4. The page
-----------

.. literalinclude:: ../../examples/todos/views/pages/todos.py
   :pyobject: Todos

* ``auth="required"`` sends anonymous visitors to ``/login?next=/``.
* ``key=f"form-{self.form_version}"`` clears the form after adding.
* ``self.run_js(js.focus(...))`` puts the cursor back in the input once the page has updated.

5. Composition
--------------

.. literalinclude:: ../../examples/todos/app.py
   :caption: app.py

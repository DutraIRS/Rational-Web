"""Todos: the composition root.

Run:  pip install "rational[db]"
      python app.py --dev     # hot reload, readable errors
      python app.py --prod    # production server
"""

from rational import App

from models import create_tables, database
from services import TodoService
from views.pages import router
from views.styles import THEME

app = App(title="Todos", theme=THEME, database=database, login_path="/login")
app.include(router)  # the pages
app.service(TodoService)  # also expose the service as a JSON API: /api/todo/... (docs at /api/docs)
app.on_startup(create_tables)

if __name__ == "__main__":
    app.run()

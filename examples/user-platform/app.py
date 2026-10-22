"""User platform: the composition root.

Run:  pip install "rational[db]"
      python app.py --dev     # hot reload, readable errors
      python app.py --prod    # production server
"""

from rational import App

from models import create_tables, database
from services import AccountService, AdminService, current_user
from views.pages import router
from views.styles import THEME

app = App(
    title="User platform",
    description="Accounts, sessions and roles, built with Rational Web.",
    theme=THEME,
    database=database,
    login_path="/login",
)
app.authenticate(current_user)  # who is signed in, loaded from the database on every request
app.include(router)
app.service(AccountService)  # JSON API under /api/account/..., docs at /api/docs
app.service(AdminService)  # /api/admin/...
app.on_startup(create_tables)

if __name__ == "__main__":
    app.run()

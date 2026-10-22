"""The composition root: build the app from its parts.

Run:  python app.py --dev     # hot reload, readable errors
      python app.py --prod    # production server
"""

from rational import App

from models import create_tables, database
from services import GuestbookService
from views.pages import router

app = App(title="Guestbook", theme="soft", database=database)
app.include(router)
app.service(GuestbookService)
app.on_startup(create_tables)

if __name__ == "__main__":
    app.run()

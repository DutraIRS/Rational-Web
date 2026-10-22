"""CV & portfolio: the composition root. Make the site yours by editing ``content.py``.

Run:  python app.py --dev     # hot reload, readable errors
      python app.py --prod    # production server
"""

from rational import App

from content import PROFILE
from services import ContactService
from views.pages import router
from views.styles import THEME

app = App(title=PROFILE.name, theme=THEME)
app.include(router)
app.service(ContactService)  # POST /api/contact/send, docs at /api/docs

if __name__ == "__main__":
    app.run()

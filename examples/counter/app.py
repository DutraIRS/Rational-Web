"""Counter: the composition root.

Run:  python app.py --dev     # hot reload, readable errors
      python app.py --prod    # production server
"""

from rational import App

from views.pages import router
from views.styles import THEME

app = App(title="Counter", theme=THEME)
app.include(router)

if __name__ == "__main__":
    app.run()

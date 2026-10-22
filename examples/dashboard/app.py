"""Dashboard: the composition root.

Run:  python app.py --dev     # hot reload, readable errors
      python app.py --prod    # production server
"""

from rational import App

from services import MetricsService
from views.pages import router
from views.styles import THEME

app = App(title="Dashboard", theme=THEME)
app.include(router)
app.service(MetricsService)  # GET /api/metrics/overview?days=30, docs at /api/docs

if __name__ == "__main__":
    app.run()

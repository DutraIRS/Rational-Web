"""Social network: the composition root.

Run:  pip install "rational[db]"
      python app.py --dev     # hot reload, readable errors
      python app.py --prod    # production server
"""

from rational import App

from models import create_tables, database
from services import SocialService, seed_network
from views.pages import router

app = App(title="Murmur", description="Posts, likes and follows.", database=database, login_path="/login")
app.include(router)
app.service(SocialService)  # JSON API under /api/social/..., docs at /api/docs
app.on_startup(create_tables)
app.on_startup(seed_network)

if __name__ == "__main__":
    app.run()

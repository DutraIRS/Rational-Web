"""Media: images, favicons, links, embedded documents and videos.

Run:  python app.py --dev     # hot reload, readable errors
      python app.py --prod    # production server

Needs internet access: every asset below is loaded from a public URL, which is the point.
"""

from rational import App

from settings import FAVICON, STATIC_DIR
from views.pages import router

app = App(title="Media", description="Images, favicons, links, embeds.", favicon=FAVICON)
app.include(router)
app.static("/static", STATIC_DIR)

if __name__ == "__main__":
    app.run()

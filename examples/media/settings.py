"""Settings, read once from the environment."""

from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
STATIC_DIR = PROJECT_DIR / "static"

FAVICON = "https://upload.wikimedia.org/wikipedia/commons/c/c3/Python-logo-notext.svg"
FAVICON_CHOICES = (
    ("Python", FAVICON),
    ("Python wordmark", "https://www.python.org/static/community_logos/python-logo-generic.svg"),
    ("GNU", "https://www.gnu.org/graphics/heckert_gnu.svg"),
)

# Verified stable, public, hotlink-friendly URLs (2026-10).
LOGO_SVG = "https://www.python.org/static/community_logos/python-logo-generic.svg"
PHOTO_JPG = "https://picsum.photos/id/237/600/400.jpg"  # fixed placeholder photo
VIDEO_MP4 = "https://interactive-examples.mdn.mozilla.net/media/cc0-videos/flower.mp4"
VIDEO_WEBM = "https://interactive-examples.mdn.mozilla.net/media/cc0-videos/flower.webm"
PDF_DOC = "https://pdfobject.com/pdf/sample.pdf"

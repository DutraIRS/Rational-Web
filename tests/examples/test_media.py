"""The media example: images, links, video and document embeds render as HTML."""

import pytest

from rational.testing import TestClient


@pytest.fixture
def media(example):
    return example("media")


def test_media_page_shows_all_embeds(media):
    with TestClient(media.app) as client:
        page = client.open("/")
        html = page.html
        # favicon in the document head
        assert 'rel="icon"' in html and "Python-logo-notext.svg" in html
        assert "heckert_gnu.svg" in html and "python-logo-generic.svg" in html
        # local static file and remote images
        assert 'src="/static/logo.svg"' in html
        assert "picsum.photos" in html
        # external links carry the safety attributes
        assert 'target="_blank"' in html and 'rel="noopener noreferrer"' in html
        assert 'href="mailto:' in html
        # video with two sources and controls; the PDF in an iframe
        assert "<video" in html and 'type="video/mp4"' in html and 'type="video/webm"' in html
        assert "<iframe" in html and "pdfobject.com/pdf/sample.pdf" in html
        assert "w3.org/WAI/ER" not in html


def test_local_static_file_is_served(media):
    with TestClient(media.app) as client:
        response = client.http.get("/static/logo.svg")
        assert response.status_code == 200 and "svg" in response.headers.get("content-type", "")


def test_internal_link_navigates(media):
    with TestClient(media.app) as client:
        assert "About this example" in client.open("/about").text

Media and embeds
================

A compact reference for loading local and remote images, setting a favicon, making internal and
external links, playing video, and embedding a PDF. Every remote URL was checked when the example
was written; the app needs internet access to display those resources.

.. code-block:: text

   media/
   ├── app.py             # favicon + local static-files mount
   ├── settings.py        # the remote asset URLs in one place
   ├── static/
   │   └── logo.svg       # a downloaded local asset
   └── views/
       ├── styles/
       └── pages/media.py # images, links, video and document embeds

1. Favicon and local files
--------------------------

Set a favicon with a local or remote URL. Mount a local directory once, then address files under
that URL prefix:

.. literalinclude:: ../../examples/media/app.py
   :caption: app.py

This example keeps three verified favicon choices in ``settings.py`` and displays all three on the
page. An application still has one active favicon at a time; choose it by changing ``FAVICON``.

2. Images
---------

.. literalinclude:: ../../examples/media/views/pages/media.py
   :pyobject: Media.render

``Image`` accepts local paths and complete remote URLs. ``alt`` is required: describe meaningful
images; use ``alt=""`` only for decoration. It adds lazy loading and asynchronous decoding by
default. Width and height attributes prevent layout shifts; ``Style`` can size scalable SVGs.

3. Links
--------

``Link(..., href="/about")`` navigates inside the app. A complete URL with ``external=True`` opens
in a new tab and automatically adds ``rel="noopener noreferrer"``. ``mailto:`` and ``tel:`` use
the same ``href`` field. Use ``ButtonLink`` when navigation should look like a button; reserve
``Button`` for actions.

4. Videos and documents
-----------------------

Rational's named primitives cover common accessible elements. The ``h()`` escape hatch builds
anything else:

.. code-block:: python

   h(
       "video",
       h("source", src=VIDEO_MP4, type="video/mp4"),
       h("source", src=VIDEO_WEBM, type="video/webm"),
       "Your browser cannot play this video.",
       controls=True,
       style=Style(width="100%"),
   )

   h(
       "iframe",
       src=PDF_DOC,
       title="An example PDF document",
       style=Style(width="100%", height=340),
   )

Multiple video sources let the browser choose a supported format. An iframe needs a useful
``title`` for accessibility. Third-party sites may forbid iframe embedding with their security
headers; in that case, provide an external ``Link`` instead.

Run it
------

.. code-block:: console

   $ cd examples/media
   $ python app.py --dev

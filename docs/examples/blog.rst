Blog
====

Fast public pages, comments, an editor with live preview, an RSS feed and a JSON API.

.. code-block:: text

   blog/
   ├── app.py            # composition root
   ├── settings.py       # DATABASE_URL, BLOG_NAME
   ├── models/           # database.py, account.py, post.py, comment.py
   ├── services/         # blog.py (BlogService), seed.py
   └── views/
       ├── components/   # markup.py (slugify + safe Markdown subset), shell, post_list, comments, editor
       ├── pages/        # public.py, admin.py, feed.py (/feed.xml, a FastAPI router)
       └── styles/

1. Rich text that is safe by construction
-----------------------------------------

.. literalinclude:: ../../examples/blog/views/components/markup.py
   :pyobject: render_body

The body becomes headings, lists and paragraphs, built from *nodes*, not HTML strings. Every
piece of text is escaped, so a post containing ``<script>`` shows it as text.

2. Drafts that don't exist for readers
--------------------------------------

.. literalinclude:: ../../examples/blog/services/blog.py
   :pyobject: BlogService.get_post

Readers get the same 404 for a draft as for a missing post.

3. Zero-JavaScript pages
------------------------

.. literalinclude:: ../../examples/blog/views/pages/public.py
   :pyobject: Index

The index has no event handlers, so the browser receives HTML and CSS only. A post page loads the
runtime just for its comment form:

.. literalinclude:: ../../examples/blog/views/components/comments.py
   :pyobject: Comments

4. Live preview
---------------

.. literalinclude:: ../../examples/blog/views/components/editor.py
   :pyobject: Editor

As you type, the debounced ``on_input`` handlers update ``body`` and ``heading``, and the
preview re-renders with the same ``render_body`` the public page uses: what you see is exactly
what readers will get.

5. The escape hatch
-------------------

.. literalinclude:: ../../examples/blog/views/pages/feed.py
   :caption: views/pages/feed.py

Anything that isn't a page (feeds, webhooks, file downloads) is a plain FastAPI route:

.. literalinclude:: ../../examples/blog/app.py
   :caption: app.py

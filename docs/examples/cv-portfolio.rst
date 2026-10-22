CV & portfolio
==============

A one-page personal site. To make it yours, edit one file: ``content.py``.

.. code-block:: text

   cv-portfolio/
   ├── app.py               # composition root
   ├── content.py           # the CV, as data
   ├── models/              # profile.py, contact.py (the form's rules)
   ├── services/            # contact.py (ContactService, + API)
   └── views/
       ├── components/      # header, hero, section, experience, skills, projects, contact
       ├── pages/           # home.py
       └── styles/

1. Content as data
------------------

.. literalinclude:: ../../examples/cv-portfolio/models/profile.py
   :pyobject: Profile

Components read ``PROFILE``; no personal details live in markup. A non-developer can update the
site by editing data.

2. Function components
----------------------

.. literalinclude:: ../../examples/cv-portfolio/views/components/section.py
   :caption: views/components/section.py

When a piece of UI has no state, a plain function that returns nodes is all you need. It's the
lightest way to share markup.

3. A timeline drawn with styles
-------------------------------

.. literalinclude:: ../../examples/cv-portfolio/views/components/experience.py
   :caption: views/components/experience.py

The vertical line is a ``border_left``; each dot is an absolutely positioned ``span``. No images
and no stylesheet.

4. An interactive island
------------------------

.. literalinclude:: ../../examples/cv-portfolio/views/components/projects.py
   :pyobject: Projects

Only the project filter and the contact form talk to the server. Everything else is static HTML.

5. A form that helps, and a trap for bots
-----------------------------------------

.. literalinclude:: ../../examples/cv-portfolio/models/contact.py
   :pyobject: ContactForm

.. literalinclude:: ../../examples/cv-portfolio/views/components/contact.py
   :pyobject: Contact

Custom validators produce friendly messages under each field. The hidden ``website`` field is a
*honeypot*: it's off-screen and hidden from screen readers, so only bots fill it in. The service
answers bots the same way it answers people, so they can't tell they were filtered.

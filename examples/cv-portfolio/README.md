# CV & portfolio

A one-page personal site: a CV with a timeline, skills, a filterable project gallery and a contact form.
Make it yours by editing a single file, `content.py`. It has no markup in it, only data.

```
cv-portfolio/
├── app.py                   # composition root
├── content.py               # the CV, as data: edit me
├── models/
│   ├── profile.py           # Profile, Job, Project, SocialLink
│   └── contact.py           # ContactForm (validation), Message
├── services/
│   └── contact.py           # ContactService (+ POST /api/contact/send)
└── views/
    ├── styles/
    │   ├── theme.py         # the theme preset
    │   ├── layout.py        # page width, sticky header, sections
    │   └── timeline.py      # the timeline's line and dots
    ├── components/
    │   ├── header.py        # section links and a dark-mode toggle
    │   ├── hero.py          # avatar, headline, calls to action
    │   ├── section.py       # titled, linkable section (function component)
    │   ├── experience.py    # the timeline
    │   ├── skills.py        # grouped badges
    │   ├── projects.py      # gallery with a technology filter
    │   └── contact.py       # validated form with a spam honeypot
    └── pages/
        └── home.py          # one page composing the sections
```

## What it shows

- **Content as data:** components read `PROFILE`; nothing about the person lives in markup.
- **Responsive without CSS:** the hero stacks on phones (`Row(collapse="mobile")`), grids fit the
  space (`Grid(min_column_width=...)`), and the section links hide on small screens.
- **Pure-style visuals:** the timeline's line and dots are `Style` objects in `views/styles/timeline.py`,
  with no images or custom CSS.
- **Small interactive islands:** only the project filter and the contact form talk to the server.
- **Forms that help:** Pydantic rules with friendly messages, shown under each field.
- **A spam honeypot:** a hidden field people never fill in; bots do, and are silently ignored.
- **Browser-only dark mode:** `js.toggle_theme()` remembers your choice in a cookie.

## Run it

```console
$ cd examples/cv-portfolio
$ python app.py --dev
```

Messages are logged to the console; this demo has no email backend.

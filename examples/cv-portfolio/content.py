"""The CV, as plain data. Edit this file to make the site yours: no markup lives here."""

from models import Job, Profile, Project, SocialLink

PROFILE = Profile(
    name="Alex Rivera",
    role="Full-stack Python engineer",
    location="Lisbon, Portugal · remote friendly",
    email="alex@example.com",
    summary=(
        "I build calm, fast web products with Python: data-heavy back ends, accessible interfaces "
        "and the tooling in between. Ten years of shipping, mentoring and keeping things simple."
    ),
    links=(
        SocialLink("GitHub", "https://github.com/"),
        SocialLink("LinkedIn", "https://www.linkedin.com/"),
        SocialLink("Blog", "https://example.com/blog"),
    ),
    jobs=(
        Job(
            "Staff engineer",
            "Northwind Analytics",
            "2022 – now",
            "Remote",
            (
                "Led the move from a SPA + REST API to server-rendered Python, halving page weight.",
                "Designed the event pipeline that ingests 40M records a day.",
                "Mentored six engineers; two now lead teams.",
            ),
        ),
        Job(
            "Senior developer",
            "Contoso Health",
            "2018 – 2022",
            "Porto",
            (
                "Built the patient portal used by 300k people, WCAG 2.1 AA compliant.",
                "Cut CI time from 40 to 9 minutes with test sharding and caching.",
            ),
        ),
        Job(
            "Developer",
            "Fabrikam Studio",
            "2015 – 2018",
            "Lisbon",
            ("Shipped e-commerce sites for 20+ clients.", "Introduced typed Python and code review."),
        ),
    ),
    skills={
        "Languages": ("Python", "TypeScript", "SQL"),
        "Back end": ("FastAPI", "SQLAlchemy", "PostgreSQL", "Redis"),
        "Front end": ("HTML", "CSS", "Accessibility", "Rational Web"),
        "Practices": ("Testing", "CI/CD", "Observability", "Mentoring"),
    },
    projects=(
        Project("Tidewatch", "Real-time tide and swell dashboard for surfers.", ("Python", "FastAPI", "Redis")),
        Project("Ledgerly", "Double-entry bookkeeping for freelancers.", ("Python", "PostgreSQL", "Rational Web")),
        Project("A11y Lint", "Catches accessibility mistakes in pull requests.", ("TypeScript", "Accessibility")),
        Project("Mapster", "Offline-first maps for field researchers.", ("TypeScript", "SQL")),
        Project("Recall", "Spaced-repetition flashcards with a tiny server.", ("Python", "SQLAlchemy", "Rational Web")),
        Project("Pulse", "Uptime monitoring with friendly alerts.", ("Python", "Redis", "Observability")),
    ),
    education=("MSc Computer Science, University of Lisbon", "BSc Informatics, University of Porto"),
)

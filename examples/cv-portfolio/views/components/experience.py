from rational import Column, Component, Heading, Row, Spacer, Style, Text, h

from .section import Section
from content import PROFILE
from views.styles import DOT, JOB, TIMELINE


class Experience(Component):
    def render(self):
        jobs = [
            h(
                "li",
                h("span", style=DOT, aria_hidden="true"),
                Row(
                    Column(Heading(job.role, level=3), Text(f"{job.company} · {job.location}", muted=True), gap=2),
                    Spacer(),
                    Text(job.period, size="sm", weight=600, color="primary"),
                    wrap=True,
                    align="start",
                ),
                h("ul", *[h("li", item) for item in job.highlights], style=Style(margin=0, padding_left="lg")),
                key=job.company,
                style=JOB,
            )
            for job in PROFILE.jobs
        ]
        education = [Text(item, muted=True) for item in PROFILE.education]
        return Section(
            "experience",
            "Experience",
            h("ol", *jobs, style=TIMELINE),
            Heading("Education", level=3) if education else None,
            *education,
        )

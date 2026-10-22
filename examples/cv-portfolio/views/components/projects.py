from rational import Badge, Button, Card, Component, Grid, Heading, Link, Row, Spacer, State, Style, Text

from .section import Section
from content import PROFILE
from models import Project


class Projects(Component):
    """Filter buttons are server events: the grid re-renders with the matching projects only."""

    technology = State("All")

    def choose(self, technology: str):
        return lambda: setattr(self, "technology", technology)

    def card(self, project: Project):
        return Card(
            Heading(project.name, level=3),
            Text(project.summary, muted=True),
            Spacer(),
            Row(*[Badge(tech) for tech in project.tech], gap="xs", wrap=True),
            Link("View project →", href=project.url, external=True) if project.url else None,
            key=project.name,
            style=Style(height="100%"),
        )

    def render(self):
        options = ["All", *PROFILE.technologies]
        shown = [p for p in PROFILE.projects if self.technology == "All" or self.technology in p.tech]
        filters = Row(
            *[
                Button(
                    tech,
                    size="sm",
                    variant="secondary" if tech == self.technology else "ghost",
                    aria_pressed="true" if tech == self.technology else "false",
                    on_click=self.choose(tech),
                )
                for tech in options
            ],
            gap="xs",
            wrap=True,
            role="group",
            aria_label="Filter projects by technology",
        )
        return Section(
            "projects",
            "Projects",
            filters,
            Text(f"{len(shown)} project{'s' if len(shown) != 1 else ''}", muted=True, size="sm", aria_live="polite"),
            Grid(*[self.card(p) for p in shown], min_column_width=260),
        )

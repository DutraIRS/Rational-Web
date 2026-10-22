"""A real site would send an email or store messages; this demo keeps an in-memory inbox."""

import logging
from datetime import UTC, datetime

from rational.backend import Service, remote

from models import Message

log = logging.getLogger("portfolio")

INBOX: list[Message] = []


class ContactService(Service):
    """The contact form, also available as an API."""

    @remote
    def send(self, name: str, email: str, message: str, website: str = "") -> bool:
        """Leave a message. Always answers ``true``, so bots can't tell they were filtered."""
        if website:  # the honeypot field was filled in: a bot
            log.info("dropped a message from a bot")
            return True
        INBOX.append(Message(name, email, message, datetime.now(UTC)))
        log.info("new message from %s <%s>", name, email)
        return True

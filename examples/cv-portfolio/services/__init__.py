"""The rules: what happens to a message. Also a JSON API (see /api/docs)."""

from .contact import INBOX, ContactService

__all__ = ["INBOX", "ContactService"]

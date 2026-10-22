"""Read and sign the guestbook; the ``@remote`` methods are also a JSON API."""

from sqlalchemy import select

from rational import FieldError
from rational.backend import Service, remote

from models import Entry, EntryRow


class GuestbookService(Service):
    """Read and sign the guestbook."""

    @remote(method="GET")
    async def entries(self) -> list[Entry]:
        """Every entry, newest first."""
        async with self.db.session() as db:
            rows = await db.scalars(select(EntryRow).order_by(EntryRow.id.desc()))
            return [Entry.model_validate(row) for row in rows]

    @remote
    async def sign(self, name: str, message: str) -> Entry:
        """Add an entry."""
        if "http://" in message or "https://" in message:
            raise FieldError("message", "Links are not allowed")
        async with self.db.transaction() as db:
            row = EntryRow(name=name.strip(), message=message.strip())
            db.add(row)
            await db.flush()
            return Entry.model_validate(row)

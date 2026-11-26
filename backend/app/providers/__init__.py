"""Mail providers: where messages come from and where label changes go."""

from typing import Protocol

from app.domain.types import Message


class MailProvider(Protocol):
    """A mailbox. Label changes are the only writes: archive removes INBOX, mark-read removes UNREAD."""

    name: str

    def fetch(self) -> list[Message]:
        """Messages currently in the inbox, newest first."""
        ...

    def modify(self, ids: list[str], add: list[str], remove: list[str]) -> None:
        """Add and remove label IDs on the given messages. Never deletes or sends."""
        ...

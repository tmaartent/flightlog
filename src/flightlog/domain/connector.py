import datetime
from dataclasses import dataclass


@dataclass(eq=False)  # an entity: equal by identity, not by its current values
class Connector:
    """A client of the read API with its own key (ADR-0005). The key itself is never stored.

    `key_prefix` identifies the key (safe to show); `key_hash` is the SHA-256 of the full key.
    A revoked connector keeps its row and its name, so audit rows still say who it was.
    """

    name: str
    key_prefix: str
    key_hash: str
    created_at: datetime.datetime
    revoked_at: datetime.datetime | None = None
    id: int | None = None  # assigned by persistence

    @property
    def is_active(self) -> bool:
        return self.revoked_at is None

    def revoke(self, now: datetime.datetime) -> None:
        """Stop the key from working. Safe to repeat: the first moment is kept."""
        if self.revoked_at is None:
            self.revoked_at = now

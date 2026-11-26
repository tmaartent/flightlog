import datetime
from dataclasses import dataclass
from enum import StrEnum


@dataclass(frozen=True)
class ConnectorRef:
    """The connector a request authenticated as: what rate limits and audit rows key on."""

    id: int
    name: str


@dataclass(frozen=True)
class IssuedKey:
    """A new connector's key. The only time the full key exists outside the client."""

    name: str
    prefix: str
    key: str


@dataclass(frozen=True)
class ConnectorInfo:
    """A connector as the admin page and `flask connector list` show it: never the hash."""

    name: str
    prefix: str
    created_at: datetime.datetime
    revoked_at: datetime.datetime | None


class RevokeOutcome(StrEnum):
    REVOKED = "revoked"
    ALREADY_REVOKED = "already_revoked"
    NOT_FOUND = "not_found"

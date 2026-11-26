import datetime
from dataclasses import dataclass
from enum import StrEnum


class ActorKind(StrEnum):
    CONNECTOR = "connector"  # a read API client with a valid key
    ADMIN = "admin"  # the one person logged in to the dashboard
    ANONYMOUS = "anonymous"  # no valid key, no login


class AuditOutcome(StrEnum):
    """Derived from the HTTP status when the log is read, never stored (ADR-0015)."""

    OK = "ok"
    DENIED = "denied"
    LIMITED = "limited"
    ERROR = "error"

    @classmethod
    def of(cls, status: int) -> "AuditOutcome":
        if status < 400:
            return cls.OK  # a 302 is the Post/Redirect/Get after an admin action
        if status in (401, 403):
            return cls.DENIED
        if status == 429:
            return cls.LIMITED
        return cls.ERROR


@dataclass(frozen=True)
class AuditEntry:
    """One audited request, as written: who, what, which object, outcome. The time is the DB's."""

    actor_kind: ActorKind
    connector_id: int | None
    ip: str | None
    method: str
    endpoint: str | None  # the Flask endpoint, e.g. "read_api.session"; None when no route matched
    path: str
    object_type: str | None
    object_id: str | None
    status: int


@dataclass(frozen=True)
class AuditRecord:
    """One row of the audit log as the admin page shows it."""

    id: int
    occurred_at: datetime.datetime
    actor_kind: ActorKind
    connector_name: str | None
    ip: str | None
    method: str
    endpoint: str | None
    path: str
    object_type: str | None
    object_id: str | None
    status: int

    @property
    def outcome(self) -> AuditOutcome:
        return AuditOutcome.of(self.status)


@dataclass(frozen=True)
class AuditFilter:
    """Which rows to list, newest first. `before` is the last id of the previous page."""

    connector: str | None = None  # a connector's name
    outcome: AuditOutcome | None = None
    before: int | None = None
    limit: int = 100


@dataclass(frozen=True)
class AuditPage:
    records: list[AuditRecord]
    next_before: int | None  # None on the last page

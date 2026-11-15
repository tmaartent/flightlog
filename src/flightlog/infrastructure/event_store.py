from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from flightlog.domain import RecordedEvent
from flightlog.infrastructure.tables import event_logs


class SqlEventStore:
    """EventStore on PostgreSQL."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add_if_new(self, event: RecordedEvent) -> int | None:
        # One atomic statement: a check-then-insert would race between two deliveries.
        statement = (
            insert(event_logs)
            .values(
                source=event.source,
                delivery_id=event.delivery_id,
                type=event.type,
                occurred_at=event.occurred_at,
                payload=event.payload,
            )
            .on_conflict_do_nothing(index_elements=["source", "delivery_id"])
            .returning(event_logs.c.id)
        )
        event_id = self._session.scalar(statement)
        if event_id is not None:
            event.id = event_id
        return event_id

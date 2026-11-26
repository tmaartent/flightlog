"""The audit log in PostgreSQL: written in its own transaction, read newest first."""

import datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from flightlog.application.api_keys import issue_key
from flightlog.contracts.audit import ActorKind, AuditEntry, AuditFilter, AuditOutcome
from flightlog.infrastructure.audit_log import SqlAuditLog, SqlAuditQueries
from flightlog.infrastructure.tables import audit_log
from flightlog.infrastructure.unit_of_work import SqlUnitOfWork

NOW = datetime.datetime(2026, 11, 26, 10, 0, tzinfo=datetime.UTC)


def entry(status: int = 200, connector_id: int | None = None, **fields) -> AuditEntry:
    values = {
        "actor_kind": ActorKind.CONNECTOR if connector_id else ActorKind.ANONYMOUS,
        "connector_id": connector_id,
        "ip": "127.0.0.1",
        "method": "GET",
        "endpoint": "read_api.sessions",
        "path": "/api/v1/sessions",
        "object_type": None,
        "object_id": None,
        "status": status,
        **fields,
    }
    return AuditEntry(**values)


@pytest.fixture
def sessions(db_connection):
    """Sessions on the test's connection: the audit log opens its own, like in production."""
    return sessionmaker(bind=db_connection, join_transaction_mode="create_savepoint")


@pytest.mark.db
def test_an_entry_is_committed_in_its_own_transaction(sessions, db_session):
    SqlAuditLog(sessions).record(entry(object_type="session", object_id="42"))

    row = db_session.execute(select(audit_log)).one()
    assert row.actor_kind is ActorKind.ANONYMOUS
    assert row.object_type == "session"
    assert row.object_id == "42"
    assert row.status == 200
    assert row.occurred_at is not None  # the database clock


@pytest.mark.db
def test_entries_are_listed_newest_first_with_the_connector_name(sessions, db_session):
    uow = SqlUnitOfWork(db_session)
    issue_key("ci-script", uow, NOW)
    connector_id = uow.connectors.get_by_name("ci-script").id
    log = SqlAuditLog(sessions)
    log.record(entry(401))
    log.record(entry(200, connector_id=connector_id))

    page = SqlAuditQueries(db_session).list_entries(AuditFilter())

    assert [(r.status, r.connector_name) for r in page.records] == [
        (200, "ci-script"),
        (401, None),
    ]
    assert page.records[0].outcome is AuditOutcome.OK
    assert page.records[1].outcome is AuditOutcome.DENIED
    assert page.next_before is None


@pytest.mark.db
@pytest.mark.parametrize(
    ("outcome", "statuses"),
    [
        (AuditOutcome.OK, [302, 200]),
        (AuditOutcome.DENIED, [403, 401]),
        (AuditOutcome.LIMITED, [429]),
        (AuditOutcome.ERROR, [500, 404, 400]),
    ],
)
def test_entries_are_filtered_by_outcome(sessions, db_session, outcome, statuses):
    log = SqlAuditLog(sessions)
    for status in [200, 302, 400, 401, 403, 404, 429, 500]:
        log.record(entry(status))

    page = SqlAuditQueries(db_session).list_entries(AuditFilter(outcome=outcome))

    assert [r.status for r in page.records] == statuses


@pytest.mark.db
def test_entries_are_filtered_by_connector(sessions, db_session):
    uow = SqlUnitOfWork(db_session)
    issue_key("one", uow, NOW)
    issue_key("two", uow, NOW)
    one, two = uow.connectors.get_by_name("one").id, uow.connectors.get_by_name("two").id
    log = SqlAuditLog(sessions)
    log.record(entry(connector_id=one, path="/one"))
    log.record(entry(connector_id=two, path="/two"))

    page = SqlAuditQueries(db_session).list_entries(AuditFilter(connector="two"))

    assert [r.path for r in page.records] == ["/two"]


@pytest.mark.db
def test_pages_continue_before_the_last_id(sessions, db_session):
    log = SqlAuditLog(sessions)
    for n in range(5):
        log.record(entry(path=f"/{n}"))
    queries = SqlAuditQueries(db_session)

    seen, before = [], None
    while True:
        page = queries.list_entries(AuditFilter(before=before, limit=2))
        seen += [r.path for r in page.records]
        if page.next_before is None:
            break
        before = page.next_before

    assert seen == ["/4", "/3", "/2", "/1", "/0"]
    assert db_session.scalar(select(func.count()).select_from(audit_log)) == 5

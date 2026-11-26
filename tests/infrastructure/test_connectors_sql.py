"""Connectors in PostgreSQL: the repository, the read side and the unique constraints."""

import datetime

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from flightlog.application.api_keys import authenticate, issue_key, revoke_key
from flightlog.contracts.connectors import ConnectorInfo
from flightlog.domain import Connector
from flightlog.infrastructure.connector_repository import (
    SqlConnectorQueries,
    SqlConnectorRepository,
)
from flightlog.infrastructure.tables import connectors
from flightlog.infrastructure.unit_of_work import SqlUnitOfWork

T0 = datetime.datetime(2026, 11, 26, 10, 0, tzinfo=datetime.UTC)
T1 = T0 + datetime.timedelta(hours=1)


@pytest.mark.db
def test_a_key_issued_and_revoked_through_the_unit_of_work(db_session):
    uow = SqlUnitOfWork(db_session)
    issued = issue_key("ci-script", uow, T0)

    assert authenticate(issued.key, uow).name == "ci-script"

    revoke_key("ci-script", uow, T1)

    assert authenticate(issued.key, uow) is None
    row = db_session.execute(select(connectors)).one()
    assert row.key_prefix == issued.prefix
    assert len(row.key_hash) == 64
    assert issued.key not in row  # only the hash is stored
    assert row.revoked_at == T1


@pytest.mark.db
def test_the_repository_finds_by_prefix_and_by_name(db_session):
    repository = SqlConnectorRepository(db_session)
    repository.add(Connector("ci-script", "0a1b2c3d", "f" * 64, created_at=T0))
    db_session.flush()

    assert repository.get_by_prefix("0a1b2c3d").name == "ci-script"
    assert repository.get_by_name("ci-script").key_prefix == "0a1b2c3d"
    assert repository.get_by_prefix("ffffffff") is None
    assert repository.get_by_name("nobody") is None


@pytest.mark.db
@pytest.mark.parametrize(
    ("name", "prefix"),
    # Values, not Connector objects: an instance made before start_mappers() isn't mapped.
    [("ci-script", "11111111"), ("other", "0a1b2c3d")],
    ids=["same name", "same prefix"],
)
def test_names_and_prefixes_are_unique(db_session, name, prefix):
    repository = SqlConnectorRepository(db_session)
    repository.add(Connector("ci-script", "0a1b2c3d", "f" * 64, created_at=T0))
    db_session.flush()

    repository.add(Connector(name, prefix, "e" * 64, created_at=T0))
    with pytest.raises(IntegrityError):
        db_session.flush()


@pytest.mark.db
def test_connectors_are_listed_oldest_first_without_their_hash(db_session):
    repository = SqlConnectorRepository(db_session)
    repository.add(Connector("newer", "22222222", "e" * 64, created_at=T1))
    repository.add(Connector("older", "11111111", "f" * 64, created_at=T0, revoked_at=T1))
    db_session.flush()

    assert SqlConnectorQueries(db_session).list_connectors() == [
        ConnectorInfo(name="older", prefix="11111111", created_at=T0, revoked_at=T1),
        ConnectorInfo(name="newer", prefix="22222222", created_at=T1, revoked_at=None),
    ]

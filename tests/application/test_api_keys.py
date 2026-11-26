import datetime
import re

import pytest

from flightlog.application.api_keys import (
    ConnectorNameTaken,
    authenticate,
    hash_key,
    issue_key,
    revoke_key,
)
from flightlog.contracts.connectors import ConnectorRef, RevokeOutcome
from tests.application.fakes import FakeUnitOfWork

T0 = datetime.datetime(2026, 11, 26, 10, 0, tzinfo=datetime.UTC)
T1 = T0 + datetime.timedelta(hours=1)


def test_an_issued_key_has_the_documented_shape():
    issued = issue_key("ci-script", FakeUnitOfWork(), T0)

    assert re.fullmatch(r"fl_[0-9a-f]{8}_[A-Za-z0-9_-]{43}", issued.key)
    assert issued.key.startswith(f"fl_{issued.prefix}_")
    assert issued.name == "ci-script"


def test_only_the_hash_and_the_prefix_are_stored():
    uow = FakeUnitOfWork()
    issued = issue_key("ci-script", uow, T0)

    stored = uow.connectors.get_by_name("ci-script")
    assert stored.key_prefix == issued.prefix
    assert stored.key_hash == hash_key(issued.key)
    assert issued.key not in vars(stored).values()
    assert stored.created_at == T0
    assert uow.commits == 1


def test_every_key_is_different():
    uow = FakeUnitOfWork()
    first = issue_key("one", uow, T0)
    second = issue_key("two", uow, T0)

    assert first.key != second.key
    assert first.prefix != second.prefix


def test_a_name_is_used_once_even_after_revoking():
    uow = FakeUnitOfWork()
    issue_key("ci-script", uow, T0)
    revoke_key("ci-script", uow, T1)

    with pytest.raises(ConnectorNameTaken):
        issue_key("ci-script", uow, T1)


@pytest.mark.parametrize("name", ["", "   "])
def test_a_connector_needs_a_name(name):
    with pytest.raises(ValueError):
        issue_key(name, FakeUnitOfWork(), T0)


def test_the_issued_key_authenticates_its_connector():
    uow = FakeUnitOfWork()
    issued = issue_key("ci-script", uow, T0)

    found = authenticate(issued.key, uow)

    connector_id = uow.connectors.get_by_name("ci-script").id
    assert found == ConnectorRef(id=connector_id, name="ci-script")


def test_a_wrong_secret_with_a_known_prefix_is_refused():
    uow = FakeUnitOfWork()
    issued = issue_key("ci-script", uow, T0)

    assert authenticate(f"fl_{issued.prefix}_{'x' * 43}", uow) is None


@pytest.mark.parametrize(
    "raw_key",
    [
        "",
        "fl_",
        "fl_0a1b2c3d",
        "fl_0a1b2c3d_",
        "xx_0a1b2c3d_secret",
        "fl_NOTHEX!!_secret",
        "fl_0a1b2c3d_secret",  # well-formed, but no such prefix
    ],
)
def test_malformed_or_unknown_keys_are_refused(raw_key):
    assert authenticate(raw_key, FakeUnitOfWork()) is None


def test_a_revoked_key_is_refused():
    uow = FakeUnitOfWork()
    issued = issue_key("ci-script", uow, T0)

    assert revoke_key("ci-script", uow, T1) is RevokeOutcome.REVOKED
    assert authenticate(issued.key, uow) is None
    assert uow.connectors.get_by_name("ci-script").revoked_at == T1


def test_revoking_is_safe_to_repeat():
    uow = FakeUnitOfWork()
    issue_key("ci-script", uow, T0)
    revoke_key("ci-script", uow, T1)

    later = T1 + datetime.timedelta(hours=1)
    assert revoke_key("ci-script", uow, later) is RevokeOutcome.ALREADY_REVOKED
    assert uow.connectors.get_by_name("ci-script").revoked_at == T1


def test_revoking_an_unknown_connector_changes_nothing():
    assert revoke_key("nobody", FakeUnitOfWork(), T1) is RevokeOutcome.NOT_FOUND

import datetime

from flightlog.domain import Connector

T0 = datetime.datetime(2026, 11, 26, 10, 0, tzinfo=datetime.UTC)


def connector() -> Connector:
    return Connector("ci-script", "0a1b2c3d", "f" * 64, created_at=T0)


def test_a_new_connector_is_active():
    assert connector().is_active


def test_a_revoked_connector_is_not_active():
    c = connector()
    c.revoke(T0 + datetime.timedelta(hours=1))

    assert not c.is_active
    assert c.revoked_at == T0 + datetime.timedelta(hours=1)


def test_revoking_twice_keeps_the_first_moment():
    c = connector()
    c.revoke(T0 + datetime.timedelta(hours=1))
    c.revoke(T0 + datetime.timedelta(hours=2))

    assert c.revoked_at == T0 + datetime.timedelta(hours=1)

import pytest
from sqlalchemy import Engine, QueuePool

from flightlog.db import get_session


def test_engine_uses_the_configured_database_url(app):
    engine: Engine = app.extensions["db"]

    assert engine.url.render_as_string(hide_password=False) == app.config["DATABASE_URL"]


def test_each_request_gets_its_own_session(app):
    with app.test_request_context():
        first = get_session()
        assert get_session() is first

    with app.test_request_context():
        assert get_session() is not first


@pytest.mark.db
def test_the_connection_goes_back_to_the_pool_after_a_request(app, client):
    engine: Engine = app.extensions["db"]
    assert isinstance(engine.pool, QueuePool)

    client.get("/health")  # runs SELECT 1 through get_session()

    assert engine.pool.checkedout() == 0
    assert engine.pool.checkedin() == 1

import pytest

from flightlog import create_app

# Nothing listens on port 1. Depending on the firewall the connection is refused or just
# never answered, so the test relies on the connect timeout rather than a quick refusal.
UNREACHABLE_DATABASE_URL = "postgresql+psycopg://flightlog:flightlog@127.0.0.1:1/flightlog"


@pytest.mark.db
def test_health_reports_ok_when_the_database_is_up(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.get_json() == {"status": "ok", "db": "ok"}


def test_health_reports_503_when_the_database_is_down():
    app = create_app(
        {"TESTING": True, "DATABASE_URL": UNREACHABLE_DATABASE_URL, "DB_CONNECT_TIMEOUT": 1}
    )

    response = app.test_client().get("/health")

    assert response.status_code == 503
    assert response.get_json() == {"status": "degraded", "db": "down"}


def test_app_uses_test_config(app):
    assert app.testing

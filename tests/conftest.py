import os

import pytest

from flightlog import create_app

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://flightlog:flightlog@localhost:5433/flightlog",
)


@pytest.fixture
def app():
    """A fresh app per test. test_config is applied last, so it wins over .env."""
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_URL": TEST_DATABASE_URL,
            "GITHUB_WEBHOOK_SECRET": "test-github-secret",
            "CLAUDE_HOOK_SECRET": "test-claude-secret",
        }
    )
    yield app


@pytest.fixture
def client(app):
    """Flask's test client: requests without a running server (like Django's Client)."""
    return app.test_client()


@pytest.fixture
def runner(app):
    """Invokes `flask` CLI commands in-process; used later for `worker` and `report`."""
    return app.test_cli_runner()

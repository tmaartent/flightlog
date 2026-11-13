import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, make_url, text
from sqlalchemy.orm import Session

from flightlog import create_app

# A separate database, so tests never touch the data you see in `flask run`.
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://flightlog:flightlog@localhost:5433/flightlog_test",
)

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def app(db_engine):
    """A fresh app per test. test_config is applied last, so it wins over .env.

    Depends on db_engine so the test database exists and is migrated before any request.
    """
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


def _create_test_database_if_missing(url: str) -> None:
    """CREATE DATABASE can't run inside a transaction, hence AUTOCOMMIT on the admin db."""
    target = make_url(url)
    admin = create_engine(target.set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            exists = conn.scalar(
                text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": target.database},
            )
            if not exists:
                conn.execute(text(f'CREATE DATABASE "{target.database}"'))
    finally:
        admin.dispose()


@pytest.fixture(scope="session")
def db_engine() -> Iterator[Engine]:
    """Once per test run: make sure the test database exists and is at the latest migration.

    Running the real migrations (not metadata.create_all) means every test run also
    tests the migrations.
    """
    _create_test_database_if_missing(TEST_DATABASE_URL)

    alembic_cfg = Config(str(REPO_ROOT / "alembic.ini"))
    alembic_cfg.set_main_option("sqlalchemy.url", TEST_DATABASE_URL)
    command.upgrade(alembic_cfg, "head")

    engine = create_engine(TEST_DATABASE_URL)
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(db_engine: Engine) -> Iterator[Session]:
    """A session inside a transaction that is rolled back after the test.

    The test may call commit() and rollback() as usual: with "create_savepoint" those only
    affect a SAVEPOINT inside the outer transaction, and the outer transaction is rolled
    back at the end. Nothing a test writes survives it.
    """
    connection = db_engine.connect()
    outer = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")

    yield session

    session.close()
    outer.rollback()
    connection.close()

import signal
from collections.abc import Iterator

import pytest
from alembic.config import Config
from flask import Flask
from sqlalchemy import Connection, Engine, create_engine, make_url, text
from sqlalchemy.orm import Session

from flightlog.infrastructure.mapping import start_mappers
from tests.harness import (
    REPO_ROOT,
    TEST_DATABASE_URL,
    create_database_if_missing,
    make_app,
    make_test_app,
    migrate_to_head,
)

# Its own database for the migration tests: they downgrade, which would drop the tables the
# other tests use. Created empty per test run and dropped afterwards.
MIGRATIONS_DATABASE_URL = make_url(TEST_DATABASE_URL).set(database="flightlog_migrations")


@pytest.fixture
def app(db_connection: Connection) -> Flask:
    """A fresh app per test whose requests run inside the test's transaction."""
    return make_test_app(db_connection)


@pytest.fixture
def app_factory(db_engine):
    """For tests that need an app with its own engine, or a different config."""
    return make_app


@pytest.fixture
def client(app):
    """Flask's test client: requests without a running server (like Django's Client)."""
    return app.test_client()


@pytest.fixture
def admin_client(app):
    """A test client that is logged in as the admin (ADR-0012)."""
    client = app.test_client()
    with client.session_transaction() as session:
        session["admin"] = True
    return client


@pytest.fixture
def runner(app):
    """Invokes `flask` CLI commands in-process; used later for `worker` and `report`."""
    return app.test_cli_runner()


@pytest.fixture(scope="session")
def db_engine() -> Iterator[Engine]:
    """Once per test run: make sure the test database exists and is at the latest migration.

    Running the real migrations (not metadata.create_all) means every test run also
    tests the migrations.
    """
    start_mappers()  # ORM tests use the domain classes without building an app
    create_database_if_missing(TEST_DATABASE_URL)
    migrate_to_head(TEST_DATABASE_URL)

    engine = create_engine(TEST_DATABASE_URL)
    yield engine
    engine.dispose()


@pytest.fixture
def db_connection(db_engine: Engine) -> Iterator[Connection]:
    """One connection per test, inside a transaction that is rolled back at the end."""
    connection = db_engine.connect()
    outer = connection.begin()

    yield connection

    outer.rollback()
    connection.close()


@pytest.fixture
def db_session(db_connection: Connection) -> Iterator[Session]:
    """A session on the test's connection.

    The test may call commit() and rollback() as usual: with "create_savepoint" those only
    affect a SAVEPOINT inside the outer transaction, which is rolled back after the test.
    """
    session = Session(bind=db_connection, join_transaction_mode="create_savepoint")
    yield session
    session.close()


def _admin_engine(url) -> Engine:
    """A connection to the maintenance database; CREATE/DROP DATABASE need AUTOCOMMIT."""
    return create_engine(make_url(url).set(database="postgres"), isolation_level="AUTOCOMMIT")


@pytest.fixture(scope="session")
def migrations_engine() -> Iterator[Engine]:
    """An engine on an empty, throwaway database, for testing the migrations themselves.

    Dropped and recreated first, so the migrations always start from `base`; dropped again
    after the test run. WITH (FORCE) closes leftover connections (PostgreSQL 13+).
    """
    name = MIGRATIONS_DATABASE_URL.database
    admin = _admin_engine(MIGRATIONS_DATABASE_URL)
    try:
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
            conn.execute(text(f'CREATE DATABASE "{name}"'))

        engine = create_engine(MIGRATIONS_DATABASE_URL)
        yield engine
        engine.dispose()

        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
    finally:
        admin.dispose()


@pytest.fixture
def migrations_cfg(migrations_engine: Engine) -> Config:
    """An Alembic Config pointing at the throwaway migrations database."""
    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    url = migrations_engine.url.render_as_string(hide_password=False)
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))  # ini files treat % specially
    return cfg


@pytest.fixture
def restore_signal_handlers():
    saved = {s: signal.getsignal(s) for s in (signal.SIGINT, signal.SIGTERM)}
    yield
    for s, handler in saved.items():
        signal.signal(s, handler)

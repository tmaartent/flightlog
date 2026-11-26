"""Building a test app and a migrated test database; shared by conftest.py and tests/e2e/."""

import os
from pathlib import Path

from alembic import command
from alembic.config import Config
from flask import Flask
from sqlalchemy import Connection, create_engine, make_url, text
from sqlalchemy.orm import sessionmaker
from werkzeug.security import generate_password_hash

from flightlog import create_app

REPO_ROOT = Path(__file__).resolve().parent.parent

# A separate database, so tests never touch the data you see in `flask run`.
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://flightlog:flightlog@localhost:5433/flightlog_test",
)

TEST_GITHUB_SECRET = "test-github-secret"
TEST_CLAUDE_SECRET = "test-claude-secret"
TEST_ADMIN_PASSWORD = "correct horse battery staple"
# Hashed once per test run: scrypt is slow on purpose.
TEST_ADMIN_PASSWORD_HASH = generate_password_hash(TEST_ADMIN_PASSWORD)


def make_app(**overrides) -> Flask:
    """An app with the test config. test_config is applied last, so it wins over .env."""
    return create_app(
        {
            "TESTING": True,
            "DATABASE_URL": TEST_DATABASE_URL,
            "GITHUB_WEBHOOK_SECRET": TEST_GITHUB_SECRET,
            "CLAUDE_HOOK_SECRET": TEST_CLAUDE_SECRET,
            "SECRET_KEY": "test-secret-key",
            "ADMIN_PASSWORD_HASH": TEST_ADMIN_PASSWORD_HASH,
            # Tests talk plain http to localhost; a Secure cookie would not come back.
            "SESSION_COOKIE_SECURE": False,
            **overrides,
        }
    )


def make_test_app(db_connection: Connection, **overrides) -> Flask:
    """An app whose sessions all run inside the test's transaction, with config overrides.

    get_session() in a route, the worker's sessions and the audit log's own session all use
    the same connection as the db_session fixture, so a test can post a request and then query
    what was stored. Everything is rolled back after the test, including what was committed.
    Build every test app with this: one on the real engine commits for good (an audited login
    left rows behind that way).
    """
    app = make_app(**overrides)
    app.extensions["sessionmaker"] = sessionmaker(
        bind=db_connection, join_transaction_mode="create_savepoint"
    )
    return app


def create_database_if_missing(url: str) -> None:
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


def migrate_to_head(url: str) -> None:
    """Run the real migrations (not metadata.create_all), so every test run also tests them."""
    alembic_cfg = Config(str(REPO_ROOT / "alembic.ini"))
    alembic_cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    command.upgrade(alembic_cfg, "head")

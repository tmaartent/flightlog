"""Building a test app and a migrated test database; shared by conftest.py and tests/e2e/."""

import os
from pathlib import Path

from alembic import command
from alembic.config import Config
from flask import Flask
from sqlalchemy import create_engine, make_url, text

from flightlog import create_app

REPO_ROOT = Path(__file__).resolve().parent.parent

# A separate database, so tests never touch the data you see in `flask run`.
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://flightlog:flightlog@localhost:5433/flightlog_test",
)

TEST_GITHUB_SECRET = "test-github-secret"
TEST_CLAUDE_SECRET = "test-claude-secret"


def make_app(**overrides) -> Flask:
    """An app with the test config. test_config is applied last, so it wins over .env."""
    return create_app(
        {
            "TESTING": True,
            "DATABASE_URL": TEST_DATABASE_URL,
            "GITHUB_WEBHOOK_SECRET": TEST_GITHUB_SECRET,
            "CLAUDE_HOOK_SECRET": TEST_CLAUDE_SECRET,
            **overrides,
        }
    )


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

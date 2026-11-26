"""A real HTTP server for Playwright, on its own database (ADR-0013).

The other tests run each request inside a transaction that is rolled back afterwards. That
needs one connection, and a browser's requests arrive on the server's threads, so they
can't share it. Instead the live server gets its own database, emptied before every test.
"""

import threading
from collections.abc import Iterator

import pytest
from flask import Flask
from playwright.sync_api import Page, expect
from sqlalchemy import create_engine, make_url, text
from werkzeug.serving import make_server

from tests.e2e.flows import log_in
from tests.harness import TEST_DATABASE_URL, create_database_if_missing, make_app, migrate_to_head

E2E_DATABASE_URL = (
    make_url(TEST_DATABASE_URL).set(database="flightlog_e2e").render_as_string(hide_password=False)
)

# Everything a test can create. RESTART IDENTITY so ids don't leak between tests.
TRUNCATE = text(
    "TRUNCATE event_jobs, event_logs, pull_requests, agent_sessions RESTART IDENTITY CASCADE"
)


def pytest_collection_modifyitems(items):
    """Every test in this folder is a browser test against the database."""
    for item in items:
        if "/e2e/" in item.path.as_posix():
            item.add_marker(pytest.mark.e2e)
            item.add_marker(pytest.mark.db)


@pytest.fixture(scope="session")
def e2e_app() -> Flask:
    create_database_if_missing(E2E_DATABASE_URL)
    migrate_to_head(E2E_DATABASE_URL)
    # One live server for the whole run, and most tests log in: 5 logins a minute is too few.
    return make_app(DATABASE_URL=E2E_DATABASE_URL, RATELIMIT_LOGIN="1000 per minute")


@pytest.fixture(scope="session")
def live_server(e2e_app: Flask) -> Iterator[str]:
    """Werkzeug's server in a background thread, on a free port (port 0: the OS picks one)."""
    server = make_server("127.0.0.1", 0, e2e_app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    thread.join(timeout=5)


@pytest.fixture(scope="session")
def base_url(live_server: str) -> str:
    """pytest-playwright gives the browser context this base URL: page.goto("/sessions")."""
    return live_server


@pytest.fixture(autouse=True)
def empty_database(e2e_app: Flask) -> None:
    engine = create_engine(E2E_DATABASE_URL)
    try:
        with engine.begin() as conn:
            conn.execute(TRUNCATE)
    finally:
        engine.dispose()


@pytest.fixture
def app_config(e2e_app: Flask) -> Iterator[dict]:
    """Change the live server's config for one test; restored afterwards."""
    saved = dict(e2e_app.config)
    yield e2e_app.config
    e2e_app.config.clear()
    e2e_app.config.update(saved)


@pytest.fixture
def logged_in(page: Page) -> None:
    """Log the test's browser page in as the admin, through the login form (ADR-0012)."""
    log_in(page)
    expect(page.get_by_role("button", name="Log out")).to_be_visible()

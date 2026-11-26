"""The README's screenshots, made the way the browser tests run: `python -m tests.e2e.screenshots`.

Seeds its own database (`flightlog_screenshots`, emptied first) through the front door, like
production data arrives: signed hook events, signed GitHub deliveries, the worker, connector
keys and a few read API calls. Then serves the app on a free port, logs in with Playwright and
saves a PNG per page to docs/images/. Run it again after a UI change; the data is the same
every time, so only real changes show up in the diff.
"""

import sys
import threading
from pathlib import Path

# pytest puts scripts/ on the path (pyproject's pythonpath); outside pytest, do the same.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from flask import Flask  # noqa: E402
from playwright.sync_api import Page, sync_playwright
from sqlalchemy import create_engine, make_url, text
from werkzeug.serving import make_server

from tests.e2e.flows import AgentSessionScript, fail_next_job, log_in, post_pull_request, run_worker
from tests.e2e.flows import at as minutes
from tests.harness import (
    REPO_ROOT,
    TEST_DATABASE_URL,
    create_database_if_missing,
    make_app,
    migrate_to_head,
)

IMAGES = REPO_ROOT / "docs" / "images"
DATABASE_URL = (
    make_url(TEST_DATABASE_URL)
    .set(database="flightlog_screenshots")
    .render_as_string(hide_password=False)
)
EVERYTHING = (
    "TRUNCATE session_digests, audit_log, connectors, event_jobs, event_logs, pull_requests,"
    " agent_sessions RESTART IDENTITY CASCADE"
)
HOUR, DAY = 60, 24 * 60


def fresh_app() -> Flask:
    create_database_if_missing(DATABASE_URL)
    migrate_to_head(DATABASE_URL)
    engine = create_engine(DATABASE_URL)
    with engine.begin() as conn:
        conn.execute(text(EVERYTHING))
    engine.dispose()
    return make_app(DATABASE_URL=DATABASE_URL, DASHBOARD_PAGE_SIZE=25)


def session(app, session_id, repo, branch, start, edits=(), commands=(), end=None):
    """One Claude Code session: its edits and Bash commands one minute apart, then SessionEnd."""
    script = AgentSessionScript(app, session_id, repo=repo, branch=branch).start(start)
    minute = start
    for path in edits:
        minute += 3
        script.edit(minute, f"/work/{repo}/{path}")
    for command in commands:
        minute += 2
        script.bash(minute, command)
    if end is not None:
        script.end(start + end)


def merged(app, repo, number, branch, title, at_minute, body=None):
    post_pull_request(
        app,
        repo=repo,
        number=number,
        branch=branch,
        title=title,
        state="closed",
        merged_at=minutes(at_minute),
        updated_at=minutes(at_minute),
        action="closed",
        body=body,
    )


def seed(app: Flask) -> None:
    # Monday 16 November 2026 onwards (ISO week 2026-W47).
    session(
        app,
        "3f2a9c1e-71b4-4c1e-9d0a-5be2f1c0a917",
        "flightlog",
        "feat/rate-limits",
        0,
        edits=[
            "src/flightlog/api/rate_limits.py",
            "src/flightlog/api/read_api.py",
            "tests/api/test_rate_limits.py",
            "src/flightlog/api/rate_limits.py",
        ],
        commands=[
            "pytest -q tests/api/test_rate_limits.py",
            "ruff check . && pytest -q",
            "GITHUB_TOKEN=ghp_9f3kQ7xLm2 gh pr create --fill",
        ],
        end=38,
    )
    merged(
        app, "flightlog", 17, "feat/rate-limits", "Rate limits per connector and on login", 2 * HOUR
    )

    session(
        app,
        "8b41d0aa-2f6e-4a8b-b3c1-0e9d7f5a2c64",
        "flightlog",
        "feat/audit-log",
        DAY + 90,
        edits=[
            "src/flightlog/api/audit.py",
            "src/flightlog/infrastructure/audit_log.py",
            "migrations/versions/8fba016aa79c_create_audit_log.py",
            "tests/api/test_audit.py",
        ],
        commands=["alembic upgrade head", "pytest -q tests/api/test_audit.py", "pytest -q"],
        end=74,
    )
    merged(
        app,
        "flightlog",
        18,
        "feat/audit-log",
        "Audit log for API calls and admin actions",
        DAY + 4 * HOUR,
    )

    session(
        app,
        "c7e92f13-5d0b-4f7e-8a21-93b6e4d1f058",
        "flightlog",
        "feat/weekly-report",
        2 * DAY + 60,
        edits=[
            "src/flightlog/api/templates/report/weekly.html",
            "src/flightlog/infrastructure/pdf.py",
            "src/flightlog/application/report.py",
        ],
        commands=["pytest -q tests/e2e/test_report_pdf.py"],
        end=52,
    )
    merged(
        app,
        "flightlog",
        19,
        "feat/weekly-report",
        "Weekly PDF report, one page per repo",
        2 * DAY + 3 * HOUR,
    )
    merged(
        app,
        "flightlog",
        20,
        "revert-19-feat/weekly-report",
        'Revert "Weekly PDF report"',
        2 * DAY + 6 * HOUR,
        body="Reverts tmaartent/flightlog#19",
    )

    session(
        app,
        "a19f4b70-6c2d-4e85-9f13-7d0c2b8e6a31",
        "shop-api",
        "fix/checkout-totals",
        3 * DAY + 30,
        edits=["src/shop/checkout.py", "src/shop/money.py", "tests/test_checkout.py"],
        commands=["npm test", "npm test -- checkout"],
        end=27,
    )
    post_pull_request(
        app,
        repo="shop-api",
        number=4,
        branch="fix/checkout-totals",
        title="Round checkout totals per line, not per order",
        updated_at=minutes(3 * DAY + 70),
    )

    session(
        app,
        "d02c8e51-9a7f-4b36-8e40-1f5d6c3b9a27",
        "shop-api",
        "chore/deps",
        3 * DAY + 4 * HOUR,
        edits=["package.json", "package-lock.json"],
        commands=["npm install", "npm test"],
        end=12,
    )

    # Still running: no SessionEnd yet.
    session(
        app,
        "e5d1b6f0-3a8c-4d27-b9e6-28f0c4a1d7b3",
        "flightlog",
        "feat/mcp-server",
        4 * DAY + 60,
        edits=["src/flightlog/api/mcp_server.py", ".mcp.json"],
        commands=["pytest -q tests/api/test_mcp_server.py"],
    )
    run_worker(app)  # applies everything above and computes the summaries

    # A delivery the worker gave up on, for the admin page.
    AgentSessionScript(app, "e5d1b6f0-3a8c-4d27-b9e6-28f0c4a1d7b3", branch="feat/mcp-server").edit(
        4 * DAY + 80, "/work/flightlog/tests/e2e/test_mcp_stdio.py"
    )
    fail_next_job(app, "OperationalError: server closed the connection unexpectedly")

    # Connectors, and a few read API calls for the audit log.
    runner = app.test_cli_runner()
    keys = {}
    for name in ["ci-script", "reporting", "old-laptop"]:
        output = runner.invoke(args=["connector", "create", name]).output
        keys[name] = next(word for word in output.split() if word.startswith("fl_"))
    runner.invoke(args=["connector", "revoke", "old-laptop"])
    client = app.test_client()
    for name, path in [
        ("ci-script", "/api/v1/sessions?repo=flightlog"),
        ("ci-script", "/api/v1/summaries?repo=flightlog&since=2026-11-01"),
        ("reporting", "/api/v1/sessions/1/summary"),
        ("old-laptop", "/api/v1/sessions"),  # revoked: 401
    ]:
        client.get(path, headers={"Authorization": f"Bearer {keys[name]}"})


def shoot(page: Page, name: str, **options) -> None:
    page.screenshot(path=str(IMAGES / f"{name}.png"), **options)
    print(f"docs/images/{name}.png")


def capture(base_url: str) -> None:
    IMAGES.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(
            base_url=base_url, viewport={"width": 1280, "height": 800}, color_scheme="light"
        )
        page = context.new_page()

        page.goto("/login")
        shoot(page, "login")
        log_in(page)

        page.goto("/sessions")
        shoot(page, "sessions", full_page=True)

        page.goto("/sessions")
        page.get_by_role("link", name="3f2a9c1e").click()
        shoot(page, "timeline", full_page=True)

        page.goto("/admin/jobs")
        shoot(page, "failed-jobs", full_page=True)
        page.goto("/admin/connectors")
        shoot(page, "connectors", full_page=True)
        page.goto("/admin/audit")
        shoot(page, "audit-log", full_page=True)

        # The report as Chromium prints it: A4 width, print styles, the first page.
        report = context.new_page()
        report.set_viewport_size({"width": 794, "height": 1123})
        report.emulate_media(media="print")
        report.goto("/reports/2026-W47")
        # The HTML doesn't paginate on screen: the first repo's section is the PDF's first page.
        report.locator("section.repo").first.screenshot(path=str(IMAGES / "weekly-report.png"))
        print("docs/images/weekly-report.png")

        dark = browser.new_context(
            base_url=base_url, viewport={"width": 1280, "height": 800}, color_scheme="dark"
        ).new_page()
        log_in(dark)
        dark.goto("/sessions")
        shoot(dark, "sessions-dark")
        browser.close()


def main() -> None:
    app = fresh_app()
    seed(app)
    server = make_server("127.0.0.1", 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        capture(f"http://127.0.0.1:{server.server_port}")
    finally:
        server.shutdown()
    with app.app_context():
        for args in (["sessions", "--repo", "flightlog", "--last", "4"],):
            print(app.test_cli_runner().invoke(args=args).output)


if __name__ == "__main__":
    Path(IMAGES).mkdir(parents=True, exist_ok=True)
    main()

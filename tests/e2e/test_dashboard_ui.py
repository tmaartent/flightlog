"""The dashboard in a real browser: what someone looking at a session clicks through."""

import re

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.flows import AgentSessionScript, at, post_pull_request, run_worker

pytestmark = pytest.mark.usefixtures("logged_in")


def session_rows(page: Page):
    return page.get_by_role("table").locator("tbody").get_by_role("row")


def test_a_session_appears_in_the_list_and_opens_on_its_timeline(page: Page, e2e_app):
    (
        AgentSessionScript(e2e_app, "3f2a9c1e-session", branch="feat/dashboard")
        .start(0)
        .edit(1, "src/flightlog/api/dashboard.py")
        .bash(2, "pytest -q")
        .end(5)
    )
    run_worker(e2e_app)

    page.goto("/sessions")
    row = session_rows(page)
    expect(row).to_have_count(1)
    expect(row).to_contain_text("flightlog")
    expect(row).to_contain_text("feat/dashboard")
    expect(row).to_contain_text("stopped")

    row.get_by_role("link", name="3f2a9c1e").click()

    expect(page).to_have_url(re.compile(r"/sessions/\d+$"))
    expect(page.get_by_role("heading", level=1)).to_contain_text("flightlog")
    files = page.get_by_role("region", name="Files touched")
    expect(files.get_by_role("listitem")).to_have_text(["src/flightlog/api/dashboard.py"])
    timeline = page.get_by_role("region", name="Timeline").get_by_role("listitem")
    expect(timeline).to_have_count(4)
    expect(timeline.nth(2)).to_contain_text("test run")
    expect(timeline.nth(2)).to_contain_text("pytest -q")
    expect(page.get_by_text("1 test run")).to_be_visible()


def test_the_list_is_filtered_by_repo_and_status(page: Page, e2e_app):
    AgentSessionScript(e2e_app, "api-session", repo="api").start(0).end(1)
    AgentSessionScript(e2e_app, "web-done", repo="web").start(2).end(3)
    AgentSessionScript(e2e_app, "web-busy", repo="web").start(4)
    run_worker(e2e_app)

    page.goto("/sessions")
    expect(session_rows(page)).to_have_count(3)

    page.get_by_label("Repo").select_option("web")
    page.get_by_label("Status").select_option("stopped")
    page.get_by_role("button", name="Filter").click()

    expect(page).to_have_url(re.compile(r"repo=web.*status=stopped"))
    expect(session_rows(page)).to_have_count(1)
    expect(session_rows(page)).to_contain_text("web-done"[:8])
    # The form shows the filter that is applied.
    expect(page.get_by_label("Repo")).to_have_value("web")
    expect(page.get_by_label("Status")).to_have_value("stopped")


def test_older_sessions_are_paged_without_repeats(page: Page, e2e_app, app_config):
    app_config["DASHBOARD_PAGE_SIZE"] = 2
    for minute, name in enumerate(["first-s", "second-", "third-se"]):
        AgentSessionScript(e2e_app, name).start(minute)
    run_worker(e2e_app)

    page.goto("/sessions")
    expect(session_rows(page)).to_have_count(2)
    expect(session_rows(page).first).to_contain_text("third-se")

    page.get_by_role("link", name="Older sessions").click()

    expect(session_rows(page)).to_have_count(1)
    expect(session_rows(page)).to_contain_text("first-s")
    expect(page.get_by_role("link", name="Older sessions")).to_have_count(0)


def test_a_merged_pull_request_shows_on_the_timeline(page: Page, e2e_app):
    """M3 acceptance: a session with a merged PR shows the PR and "merged"."""
    AgentSessionScript(e2e_app, "merged-session", branch="feat/x").start(0).end(10)
    post_pull_request(
        e2e_app,
        number=7,
        branch="feat/x",
        title="Add x",
        state="closed",
        merged_at=at(20),
        action="closed",
    )
    run_worker(e2e_app)

    open_only_session(page)

    prs = page.get_by_role("region", name="Pull requests").get_by_role("listitem")
    expect(prs).to_have_count(1)
    expect(prs).to_contain_text("#7 Add x")
    expect(prs).to_contain_text("merged")


def test_a_reverted_pull_request_shows_as_reverted(page: Page, e2e_app):
    """M3 acceptance: a reverted PR shows "reverted"."""
    AgentSessionScript(e2e_app, "reverted-session", branch="feat/x").start(0).end(10)
    post_pull_request(
        e2e_app, number=7, branch="feat/x", state="closed", merged_at=at(20), action="closed"
    )
    post_pull_request(
        e2e_app,
        number=8,
        branch="revert-7-feat/x",
        state="closed",
        merged_at=at(30),
        action="closed",
        body="Reverts tmaartent/flightlog#7",
    )
    run_worker(e2e_app)

    open_only_session(page)

    prs = page.get_by_role("region", name="Pull requests").get_by_role("listitem")
    expect(prs).to_contain_text("reverted")


def test_events_not_yet_processed_are_announced(page: Page, e2e_app):
    script = AgentSessionScript(e2e_app, "lagging-session").start(0)
    run_worker(e2e_app)
    script.edit(1, "a.py").edit(2, "b.py")  # queued, the worker hasn't run again

    open_only_session(page)

    expect(page.get_by_role("status")).to_contain_text("2 events not processed yet")
    expect(page.get_by_role("region", name="Files touched")).to_contain_text("No files edited")

    run_worker(e2e_app)
    page.reload()

    expect(page.get_by_role("status")).to_have_count(0)
    expect(page.get_by_role("region", name="Files touched").get_by_role("listitem")).to_have_count(
        2
    )


def open_only_session(page: Page) -> None:
    page.goto("/sessions")
    session_rows(page).get_by_role("link").click()

"""Logging in, and retrying a failed job, in a real browser (M3 task 3, ADR-0012)."""

import re

from playwright.sync_api import Page, expect

from tests.e2e.flows import AgentSessionScript, fail_next_job, log_in, run_worker
from tests.harness import TEST_ADMIN_PASSWORD


def test_a_page_asks_for_the_login_and_returns_after_it(page: Page, e2e_app):
    AgentSessionScript(e2e_app, "s-1").start(0)
    run_worker(e2e_app)

    page.goto("/sessions?status=active")

    expect(page).to_have_url(re.compile(r"/login\?next="))
    expect(page.get_by_role("heading", name="Log in")).to_be_visible()
    page.get_by_label("Password").fill("wrong")
    page.get_by_role("button", name="Log in").click()
    expect(page.get_by_role("alert")).to_have_text("Wrong password.")

    page.get_by_label("Password").fill(TEST_ADMIN_PASSWORD)
    page.get_by_role("button", name="Log in").click()

    expect(page).to_have_url(re.compile(r"/sessions\?status=active$"))
    expect(page.get_by_role("table").locator("tbody tr")).to_have_count(1)


def test_logging_out_locks_the_dashboard_again(page: Page):
    log_in(page)

    page.get_by_role("button", name="Log out").click()

    expect(page).to_have_url(re.compile(r"/login$"))
    page.goto("/sessions")
    expect(page).to_have_url(re.compile(r"/login\?next=/sessions$"))


def test_a_retried_job_is_processed_by_the_worker(page: Page, e2e_app):
    """M3 acceptance: the retry button re-queues a failed event, and it is then processed."""
    AgentSessionScript(e2e_app, "retried-session").start(0)
    job_id = fail_next_job(e2e_app, "OperationalError: the database restarted")
    log_in(page)

    page.get_by_role("link", name="Failed jobs").click()
    row = page.get_by_role("row").filter(has_text="the database restarted")
    expect(row).to_contain_text("SessionStart")
    row.get_by_role("button", name=f"Retry job {job_id}").click()

    expect(page.get_by_role("status")).to_contain_text(f"Job {job_id} is queued again")
    expect(page.get_by_text("No failed jobs.")).to_be_visible()

    run_worker(e2e_app)
    page.get_by_role("link", name="Sessions").click()

    rows = page.get_by_role("table").locator("tbody tr")
    expect(rows).to_have_count(1)
    expect(rows).to_contain_text("retried")
    rows.get_by_role("link").click()
    expect(page.get_by_role("region", name="Timeline")).to_contain_text("SessionStart")


def test_the_retry_button_is_refused_without_the_page_s_csrf_token(page: Page, e2e_app):
    """A form on another site can make the browser post here, but can't know the token."""
    AgentSessionScript(e2e_app, "s-1").start(0)
    job_id = fail_next_job(e2e_app)
    log_in(page)

    response = page.request.post(f"/admin/jobs/{job_id}/retry", form={"csrf_token": "guessed"})

    assert response.status == 400
    page.goto("/admin/jobs")
    expect(page.get_by_role("button", name=f"Retry job {job_id}")).to_be_visible()

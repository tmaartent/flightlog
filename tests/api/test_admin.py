"""The admin page: failed jobs and the retry button (M3 task 3, ADR-0012)."""

import pytest
from sqlalchemy import select

from flightlog.infrastructure.tables import event_jobs
from tests.session_util import add_event, at
from tests.util import csrf_token


def failed_job(db_session, external_id: str = "s-1", minutes: int = 1) -> int:
    """A job the worker gave up on, for an event of session `external_id`. Returns its id."""
    event_id = add_event(db_session, external_id, at(minutes), job=True, failed=True)
    return db_session.scalar(select(event_jobs.c.id).where(event_jobs.c.event_log_id == event_id))


def job_row(db_session, job_id: int):
    return db_session.execute(select(event_jobs).where(event_jobs.c.id == job_id)).one()


def retry(client, job_id: int, token: str | None = None):
    data = {"csrf_token": csrf_token(client) if token is None else token}
    return client.post(f"/admin/jobs/{job_id}/retry", data=data)


@pytest.mark.db
def test_failed_jobs_are_listed_with_their_error(admin_client, db_session):
    job_id = failed_job(db_session)

    response = admin_client.get("/admin/jobs")

    assert response.status_code == 200
    assert "boom" in response.text
    assert "PostToolUse" in response.text
    assert f'action="/admin/jobs/{job_id}/retry"' in response.text


@pytest.mark.db
def test_no_failed_jobs_says_so(admin_client):
    assert "No failed jobs" in admin_client.get("/admin/jobs").text


@pytest.mark.db
def test_the_error_text_is_escaped(admin_client, db_session):
    job_id = failed_job(db_session)
    db_session.execute(
        event_jobs.update()
        .where(event_jobs.c.id == job_id)
        .values(last_error="<img src=x onerror=alert(1)>")
    )

    response = admin_client.get("/admin/jobs")

    assert "<img src=x" not in response.text
    assert "&lt;img src=x" in response.text


@pytest.mark.db
def test_retry_queues_the_job_again(admin_client, db_session):
    job_id = failed_job(db_session)

    response = retry(admin_client, job_id)

    assert response.status_code == 302
    assert response.headers["Location"] == "/admin/jobs"
    row = job_row(db_session, job_id)
    assert row.failed_at is None
    assert row.attempts == 0
    page = admin_client.get("/admin/jobs")
    assert f"Job {job_id} is queued again" in page.text
    assert "No failed jobs" in page.text


@pytest.mark.db
def test_retry_without_a_csrf_token_changes_nothing(admin_client, db_session):
    job_id = failed_job(db_session)

    response = admin_client.post(f"/admin/jobs/{job_id}/retry")

    assert response.status_code == 400
    assert job_row(db_session, job_id).failed_at is not None


@pytest.mark.db
def test_retry_with_a_forged_csrf_token_changes_nothing(admin_client, db_session):
    job_id = failed_job(db_session)
    csrf_token(admin_client)

    response = retry(admin_client, job_id, token="forged")

    assert response.status_code == 400
    assert job_row(db_session, job_id).failed_at is not None


@pytest.mark.db
def test_retrying_a_job_that_is_not_failed_says_so(admin_client, db_session):
    job_id = failed_job(db_session)
    retry(admin_client, job_id)

    response = retry(admin_client, job_id)  # a double click

    assert response.status_code == 302
    assert "is not failed" in admin_client.get("/admin/jobs").text


@pytest.mark.db
def test_retry_is_not_a_get(admin_client, db_session):
    job_id = failed_job(db_session)

    assert admin_client.get(f"/admin/jobs/{job_id}/retry").status_code == 405


@pytest.mark.db
def test_retry_needs_a_login(client, db_session):
    job_id = failed_job(db_session)

    response = retry(client, job_id)

    assert response.status_code == 302
    assert response.headers["Location"].startswith("/login")
    assert job_row(db_session, job_id).failed_at is not None

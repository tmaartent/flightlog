"""The admin page: jobs the worker gave up on, and a button to retry them (M3 task 3)."""

from flask import Blueprint, current_app, flash, redirect, render_template, url_for
from flask.typing import ResponseReturnValue

from flightlog.api.auth import check_csrf, require_admin
from flightlog.application.ports import JobQueries, UnitOfWork
from flightlog.application.retry import retry_failed_job

bp = Blueprint("admin", __name__, url_prefix="/admin")
bp.before_request(require_admin)
bp.before_request(check_csrf)


@bp.get("/jobs")
def jobs() -> ResponseReturnValue:
    queries: JobQueries = current_app.extensions["job_queries"]()
    return render_template("admin/jobs.html", failed=queries.failed_jobs())


@bp.post("/jobs/<int:job_id>/retry")
def retry(job_id: int) -> ResponseReturnValue:
    uow: UnitOfWork = current_app.extensions["unit_of_work"]()
    if retry_failed_job(job_id, uow):
        flash(f"Job {job_id} is queued again. The worker picks it up within a few seconds.")
    else:
        flash(f"Job {job_id} is not failed: it was retried already or has finished.", "error")
    # Post/Redirect/Get: a reload shows the list instead of sending the POST again.
    return redirect(url_for("admin.jobs"))

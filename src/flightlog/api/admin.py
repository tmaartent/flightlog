"""Admin pages: failed jobs with a retry button (M3), and the API connectors (M4)."""

import datetime

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, url_for
from flask.typing import ResponseReturnValue

from flightlog.api.audit import audit_object
from flightlog.api.auth import check_csrf, require_admin
from flightlog.application.api_keys import revoke_connector as revoke
from flightlog.application.ports import (
    AuditQueries,
    ConnectorQueries,
    JobQueries,
    UnitOfWork,
)
from flightlog.application.retry import retry_failed_job
from flightlog.contracts.audit import AuditFilter, AuditOutcome
from flightlog.contracts.connectors import RevokeOutcome

bp = Blueprint("admin", __name__, url_prefix="/admin")
bp.before_request(require_admin)
bp.before_request(check_csrf)


@bp.get("/jobs")
def jobs() -> ResponseReturnValue:
    queries: JobQueries = current_app.extensions["job_queries"]()
    return render_template("admin/jobs.html", failed=queries.failed_jobs())


@bp.post("/jobs/<int:job_id>/retry")
def retry(job_id: int) -> ResponseReturnValue:
    audit_object("job", job_id)
    uow: UnitOfWork = current_app.extensions["unit_of_work"]()
    if retry_failed_job(job_id, uow):
        flash(f"Job {job_id} is queued again. The worker picks it up within a few seconds.")
    else:
        flash(f"Job {job_id} is not failed: it was retried already or has finished.", "error")
    # Post/Redirect/Get: a reload shows the list instead of sending the POST again.
    return redirect(url_for("admin.jobs"))


@bp.get("/connectors")
def connectors() -> ResponseReturnValue:
    queries: ConnectorQueries = current_app.extensions["connector_queries"]()
    return render_template("admin/connectors.html", connectors=queries.list_connectors())


@bp.post("/connectors/<int:connector_id>/revoke")
def revoke_connector(connector_id: int) -> ResponseReturnValue:
    audit_object("connector", connector_id)
    uow: UnitOfWork = current_app.extensions["unit_of_work"]()
    outcome = revoke(connector_id, uow, datetime.datetime.now(datetime.UTC))
    if outcome is RevokeOutcome.REVOKED:
        flash(f"Revoked connector {connector_id}. Its next request gets a 401.")
    elif outcome is RevokeOutcome.ALREADY_REVOKED:
        flash(f"Connector {connector_id} was already revoked.", "error")
    else:
        flash(f"No connector with id {connector_id}.", "error")
    return redirect(url_for("admin.connectors"))


AUDIT_PAGE_SIZE = 100


@bp.get("/audit")
def audit() -> ResponseReturnValue:
    audit_filter = parse_audit_filter(current_app.config.get("AUDIT_PAGE_SIZE", AUDIT_PAGE_SIZE))
    queries: AuditQueries = current_app.extensions["audit_queries"]()
    page = queries.list_entries(audit_filter)
    older_url = None
    if page.next_before is not None:
        older_url = url_for(
            "admin.audit",
            connector=audit_filter.connector,
            outcome=audit_filter.outcome,
            before=page.next_before,
        )
    connectors: ConnectorQueries = current_app.extensions["connector_queries"]()
    return render_template(
        "admin/audit.html",
        page=page,
        audit_filter=audit_filter,
        connectors=connectors.list_connectors(),
        outcomes=[o.value for o in AuditOutcome],
        older_url=older_url,
    )


def parse_audit_filter(limit: int) -> AuditFilter:
    """The query string as an AuditFilter; an empty field means "any", a bad value is a 400."""
    outcome = request.args.get("outcome") or None
    if outcome is not None and outcome not in AuditOutcome:
        abort(400, f"outcome must be one of: {', '.join(AuditOutcome)}")
    before = request.args.get("before") or None
    if before is not None and (not before.isdigit() or int(before) < 1):
        abort(400, "before must be an audit row id")
    return AuditFilter(
        connector=request.args.get("connector") or None,
        outcome=AuditOutcome(outcome) if outcome else None,
        before=int(before) if before else None,
        limit=limit,
    )

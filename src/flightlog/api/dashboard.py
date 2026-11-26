"""The dashboard: server-rendered pages, read-only, behind the admin login (ADR-0010, 0012)."""

import datetime

from flask import Blueprint, abort, current_app, redirect, render_template, request, url_for
from flask.typing import ResponseReturnValue

from flightlog.api.auth import check_csrf, require_admin
from flightlog.api.report import build_report, render_report_html
from flightlog.api.session_filter import STATUSES, parse_session_filter
from flightlog.application.ports import AgentSessionQueries
from flightlog.application.timeline import session_timeline
from flightlog.contracts.report import IsoWeek

bp = Blueprint("dashboard", __name__)
bp.before_request(require_admin)
bp.before_request(check_csrf)

DEFAULT_PAGE_SIZE = 25


@bp.get("/")
def index() -> ResponseReturnValue:
    return redirect(url_for("dashboard.sessions"))


@bp.get("/sessions")
def sessions() -> ResponseReturnValue:
    limit = current_app.config.get("DASHBOARD_PAGE_SIZE", DEFAULT_PAGE_SIZE)
    session_filter = parse_session_filter(request.args, limit)
    q = queries()
    page = q.list_sessions(session_filter)
    older_url = None
    if page.next_cursor is not None:
        older_url = url_for(
            "dashboard.sessions",
            repo=session_filter.repo,  # None values are left out of the URL
            status=session_filter.status,
            after=page.next_cursor.to_token(),
        )
    return render_template(
        "dashboard/sessions.html",
        page=page,
        session_filter=session_filter,
        repos=q.repos(),
        statuses=STATUSES,
        older_url=older_url,
    )


@bp.get("/sessions/<int:session_id>")
def timeline(session_id: int) -> ResponseReturnValue:
    found = session_timeline(session_id, queries())
    if found is None:
        abort(404)
    return render_template("dashboard/timeline.html", timeline=found)


@bp.get("/reports")
def reports() -> ResponseReturnValue:
    week = IsoWeek.last_full_week(datetime.datetime.now(datetime.UTC).date())
    return redirect(url_for("dashboard.report", week=str(week)))


@bp.get("/reports/<week>")
def report(week: str) -> ResponseReturnValue:
    """The weekly report as HTML: what `flask report` prints, for working on the layout."""
    try:
        iso_week = IsoWeek.parse(week)
    except ValueError:
        abort(404)
    return render_report_html(build_report(iso_week))


def queries() -> AgentSessionQueries:
    """The read side wired in by create_app (the API doesn't know which implementation)."""
    return current_app.extensions["agent_session_queries"]()


@bp.app_template_filter("utc")
def format_utc(moment: datetime.datetime | None) -> str:
    """Times are shown in UTC (ADR-0010), with the zone spelled out."""
    if moment is None:
        return ""
    return moment.astimezone(datetime.UTC).strftime("%Y-%m-%d %H:%M UTC")


@bp.app_template_filter("utc_time")
def format_utc_time(moment: datetime.datetime) -> str:
    return moment.astimezone(datetime.UTC).strftime("%H:%M:%S")


@bp.app_template_filter("duration")
def format_duration(started_at: datetime.datetime, ended_at: datetime.datetime | None) -> str:
    if ended_at is None:
        return "running"
    minutes = int((ended_at - started_at).total_seconds() // 60)
    if minutes < 60:
        return f"{minutes} min"
    return f"{minutes // 60} h {minutes % 60} min"

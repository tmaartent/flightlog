"""`flask report --week 2026-W46`: the weekly report as a PDF (ADR-0006, ADR-0016).

The HTML comes from a Jinja template rendered in-process and goes to Chromium as a string:
no server, no login, no network. The dashboard shows the same HTML at /reports/<week>.
"""

import datetime
from pathlib import Path

import click
from flask import Blueprint, current_app, render_template

from flightlog.application.ports import PdfRenderer, ReportQueries
from flightlog.application.report import weekly_report
from flightlog.contracts.report import IsoWeek, WeeklyReport

bp = Blueprint("report", __name__, cli_group=None)


def build_report(week: IsoWeek) -> WeeklyReport:
    queries: ReportQueries = current_app.extensions["report_queries"]()
    return weekly_report(week, queries, datetime.datetime.now(datetime.UTC))


def render_report_html(report: WeeklyReport) -> str:
    return render_template("report/weekly.html", report=report)


def footer(week: IsoWeek) -> str:
    return f"Flightlog · {week} · counts and paths only, never commands"


@bp.cli.command("report")
@click.option("--week", "week_text", metavar="YYYY-Www", help="ISO week; default: last full week.")
@click.option(
    "--out",
    type=click.Path(dir_okay=False, path_type=Path),
    help="Where to write the PDF; default: reports/flightlog-<week>.pdf.",
)
def report_command(week_text: str | None, out: Path | None) -> None:
    """Render the weekly report to a PDF, one page per repo."""
    try:
        week = IsoWeek.parse(week_text) if week_text else IsoWeek.last_full_week(_today())
    except ValueError as error:
        raise click.BadParameter(str(error), param_hint="--week") from None

    report = build_report(week)
    # A context processor reads flask.session, which needs a request; the CLI has none.
    with current_app.test_request_context():
        page = render_report_html(report)
    renderer: PdfRenderer = current_app.extensions["pdf_renderer"]()
    pdf = renderer.render(page, footer(week))

    out = out or Path("reports") / f"flightlog-{week}.pdf"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(pdf)
    repos = len(report.repos)
    pages = repos or 1  # a quiet week is one page that says so
    click.echo(f"Wrote {out}: {_count(repos, 'repo')}, {_count(pages, 'page')}.")


def _count(n: int, noun: str) -> str:
    return f"{n} {noun}" if n == 1 else f"{n} {noun}s"


def _today() -> datetime.date:
    return datetime.datetime.now(datetime.UTC).date()


@bp.app_template_filter("timespan")
def format_timespan(span: datetime.timedelta) -> str:
    minutes = int(span.total_seconds() // 60)
    return f"{minutes // 60} h {minutes % 60} min" if minutes >= 60 else f"{minutes} min"


@bp.app_template_filter("week_days")
def format_week_days(week: IsoWeek) -> str:
    """Monday to Sunday, as people read a week: 9 Nov – 15 Nov 2026."""
    first, last = week.start.date(), week.end.date() - datetime.timedelta(days=1)
    return f"{first.day} {first:%b} – {last.day} {last:%b %Y}"

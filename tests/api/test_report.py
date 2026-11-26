"""The weekly report: the HTML preview and `flask report` with a stand-in for Chromium."""

import datetime

import pytest

from flightlog.application.report import ROW_LIMIT
from flightlog.contracts.report import IsoWeek
from tests.session_util import add_event, add_started_session

WEEK = IsoWeek.parse("2026-W46")


def at(hours: float) -> datetime.datetime:
    return WEEK.start + datetime.timedelta(hours=hours)


def seed_week(db_session) -> None:
    """Two repos in W46, one session in W47 that must not show up."""
    api = add_started_session(db_session, "s-api", started_at=at(1), repo="api", branch="feat/x")
    add_event(
        db_session,
        "s-api",
        at(1.5),
        hook={"tool_name": "Edit", "tool_input": {"file_path": "src/app.py"}},
        session_id=api,
    )
    add_event(
        db_session,
        "s-api",
        at(1.6),
        hook={"tool_name": "Bash", "tool_input": {"command": "GITHUB_TOKEN=s3cret pytest -q"}},
        session_id=api,
    )
    add_started_session(db_session, "s-web", started_at=at(30), repo="web")
    add_started_session(db_session, "s-later", started_at=at(7 * 24 + 1), repo="later")


class FakePdfRenderer:
    calls: list[tuple[str, str]] = []

    def render(self, html_page: str, footer: str) -> bytes:
        FakePdfRenderer.calls.append((html_page, footer))
        return b"%PDF-fake"


@pytest.fixture
def fake_pdf(app):
    FakePdfRenderer.calls = []
    app.extensions["pdf_renderer"] = FakePdfRenderer
    return FakePdfRenderer


# --- the preview ----------------------------------------------------------------------------


@pytest.mark.db
def test_the_preview_shows_one_section_per_repo(admin_client, db_session):
    seed_week(db_session)

    page = admin_client.get("/reports/2026-W46")

    assert page.status_code == 200
    assert page.text.count('<section class="repo">') == 2
    assert "<h1>api</h1>" in page.text
    assert "<h1>web</h1>" in page.text
    assert "later" not in page.text
    assert "src/app.py" in page.text
    assert "9 Nov – 15 Nov 2026" in page.text


@pytest.mark.db
def test_the_report_never_copies_a_command(admin_client, db_session):
    seed_week(db_session)

    page = admin_client.get("/reports/2026-W46").text

    assert "pytest" not in page
    assert "GITHUB_TOKEN" not in page
    assert "s3cret" not in page


@pytest.mark.db
def test_a_busy_repo_is_capped_to_fit_its_page(admin_client, db_session):
    for n in range(ROW_LIMIT + 2):
        add_started_session(db_session, f"s-{n}", started_at=at(n), repo="busy")

    page = admin_client.get("/reports/2026-W46").text

    assert page.count('<td class="num">0</td>') == 2 * ROW_LIMIT  # edits and test runs per row
    assert "And 2 more sessions, counted in the totals above." in page


@pytest.mark.db
def test_a_quiet_week_says_so(admin_client):
    page = admin_client.get("/reports/2026-W46").text

    assert "No agent sessions started in 2026-W46." in page


@pytest.mark.db
@pytest.mark.parametrize("week", ["2026-W54", "2026-46", "latest"])
def test_a_bad_week_is_a_404(admin_client, week):
    assert admin_client.get(f"/reports/{week}").status_code == 404


@pytest.mark.db
def test_reports_without_a_week_go_to_the_last_full_week(admin_client):
    response = admin_client.get("/reports")

    expected = IsoWeek.last_full_week(datetime.datetime.now(datetime.UTC).date())
    assert response.status_code == 302
    assert response.headers["Location"] == f"/reports/{expected}"


@pytest.mark.db
def test_the_preview_needs_the_login(client):
    assert client.get("/reports/2026-W46").status_code == 302


# --- flask report ---------------------------------------------------------------------------


@pytest.mark.db
def test_the_command_writes_the_pdf_it_gets_from_the_renderer(
    runner, fake_pdf, db_session, tmp_path
):
    seed_week(db_session)
    out = tmp_path / "w46.pdf"

    result = runner.invoke(args=["report", "--week", "2026-W46", "--out", str(out)])

    assert result.exit_code == 0, result.output
    assert out.read_bytes() == b"%PDF-fake"
    assert f"Wrote {out}: 2 repos, 2 pages." in result.output
    ((html_page, footer),) = fake_pdf.calls
    assert "<h1>api</h1>" in html_page
    assert footer.startswith("Flightlog · 2026-W46")


@pytest.mark.db
def test_the_default_is_the_last_full_week_under_reports(runner, fake_pdf, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(args=["report"])

    week = IsoWeek.last_full_week(datetime.datetime.now(datetime.UTC).date())
    assert result.exit_code == 0, result.output
    assert (tmp_path / "reports" / f"flightlog-{week}.pdf").exists()


@pytest.mark.db
def test_a_bad_week_is_refused(runner, fake_pdf):
    result = runner.invoke(args=["report", "--week", "2026-W54"])

    assert result.exit_code != 0
    assert "2026-W54 has no week 54" in result.output
    assert fake_pdf.calls == []

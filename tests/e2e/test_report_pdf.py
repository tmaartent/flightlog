"""The report as a real PDF from headless Chromium: one page per repo (M4 acceptance).

Not a browser test against the live server, but it starts Chromium, so it runs with them.
"""

import datetime
import io
from concurrent.futures import ThreadPoolExecutor

import pytest
from pypdf import PdfReader

from flightlog.application.report import ROW_LIMIT, TOP_FILES
from flightlog.contracts.report import IsoWeek
from tests.session_util import add_event, add_started_session

WEEK = IsoWeek.parse("2026-W46")
LONG_DIRECTORY = "src/flightlog/some/deeply/nested/package"


def at(hours: float) -> datetime.datetime:
    return WEEK.start + datetime.timedelta(hours=hours)


def in_own_thread(function, *args):
    """pytest-playwright keeps its own Playwright running on this thread for the browser
    tests, and the sync API allows one per thread. The report gets a thread of its own."""
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(function, *args).result()


@pytest.mark.db
def test_the_pdf_has_one_page_per_repo_even_for_a_busy_repo(runner, db_session, tmp_path):
    # The worst case for the page: every row shown, the rest summarised, every top file, and
    # long paths and branch names.
    for n in range(ROW_LIMIT + 5):
        session_id = add_started_session(
            db_session,
            f"busy-{n}",
            started_at=at(n),
            repo="busy",
            branch=f"feature/a-rather-long-branch-name-for-session-{n}",
        )
        add_event(
            db_session,
            f"busy-{n}",
            at(n + 0.5),
            hook={
                "tool_name": "Edit",
                "tool_input": {"file_path": f"{LONG_DIRECTORY}/module_{n % (TOP_FILES + 3)}.py"},
            },
            session_id=session_id,
        )
    add_started_session(db_session, "quiet-1", started_at=at(50), repo="quiet")
    out = tmp_path / "report.pdf"

    result = in_own_thread(runner.invoke, None, ["report", "--week", str(WEEK), "--out", str(out)])

    assert result.exit_code == 0, result.output
    reader = PdfReader(io.BytesIO(out.read_bytes()))
    texts = [page.extract_text() for page in reader.pages]
    assert len(texts) == 2, texts
    assert "busy" in texts[0] and "And 5 more sessions" in texts[0]
    assert "quiet" in texts[1]
    assert "page 1 of 2" in texts[0]
    assert "page 2 of 2" in texts[1]


@pytest.mark.db
def test_a_quiet_week_is_one_page(runner, tmp_path):
    out = tmp_path / "quiet.pdf"

    result = in_own_thread(runner.invoke, None, ["report", "--week", str(WEEK), "--out", str(out)])

    assert result.exit_code == 0, result.output
    (page,) = PdfReader(io.BytesIO(out.read_bytes())).pages
    assert "No agent sessions started in 2026-W46." in page.extract_text()

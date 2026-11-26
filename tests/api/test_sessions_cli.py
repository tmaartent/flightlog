"""`flask sessions`: a screenful of recent sessions for an agent's shell (M5 task 2)."""

import dataclasses
import json
import os
import subprocess
import sys

import pytest

from flightlog.domain import AgentSessionStatus, PullRequest, PullRequestState
from flightlog.infrastructure.digest_repository import SqlDigestRepository
from flightlog.infrastructure.tables import agent_sessions
from tests.harness import TEST_DATABASE_URL
from tests.infrastructure.test_digests_sql import a_digest
from tests.session_util import add_started_session, at

LONG_PATH = "src/deeply/nested/package/module_with_a_long_name.py"


def stopped(db_session, name, minutes, branch="feat/rate-limits", digest=True, files=None):
    """A session in `shop` that ran 38 minutes, with a digest unless digest=False."""
    session_id = add_started_session(
        db_session,
        name,
        started_at=at(minutes),
        repo="shop",
        branch=branch,
        status=AgentSessionStatus.STOPPED,
    )
    db_session.execute(
        agent_sessions.update()
        .where(agent_sessions.c.id == session_id)
        .values(ended_at=at(minutes + 38))
    )
    if digest:
        stored = a_digest(session_id, 3)
        if files is not None:
            stored = dataclasses.replace(stored, files_touched=files)
        SqlDigestRepository(db_session).save(stored)
    return session_id


def pull_request(db_session, number, branch, title, state=PullRequestState.OPEN):
    db_session.add(PullRequest("shop", number, branch, title, at(50), state=state))
    db_session.flush()


def sessions(runner, *args) -> str:
    result = runner.invoke(args=["sessions", *args])
    assert result.exit_code == 0, result.output
    return result.output


@pytest.mark.db
def test_two_lines_per_session_newest_first(runner, db_session):
    stopped(db_session, "older", 0)
    stopped(db_session, "newer", 60, branch="fix/login")

    lines = sessions(runner, "--repo", "shop").splitlines()

    assert lines == [
        "Last 2 agent sessions in shop, newest first:",
        "2026-11-16 11:00 UTC · 38 min · fix/login · no PR",
        "  goal: login · 1 file (from-3-events.py) · 0 test runs",
        "2026-11-16 10:00 UTC · 38 min · feat/rate-limits · no PR",
        "  goal: rate limits · 1 file (from-3-events.py) · 0 test runs",
    ]


@pytest.mark.db
def test_the_pull_request_and_its_title_as_goal(runner, db_session):
    stopped(db_session, "s-1", 0, branch="feat/limits")
    pull_request(
        db_session, 17, "feat/limits", "Rate limits per connector", PullRequestState.MERGED
    )

    lines = sessions(runner, "--repo", "shop").splitlines()

    assert lines[1].endswith("· feat/limits · PR #17 merged")
    assert lines[2].startswith("  goal: Rate limits per connector · ")


@pytest.mark.db
def test_running_and_pending_sessions_say_so(runner, db_session):
    add_started_session(db_session, "live", started_at=at(90), repo="shop")
    stopped(db_session, "fresh", 30, digest=False)

    lines = sessions(runner, "--repo", "shop").splitlines()

    assert " · running · " in lines[1]
    assert lines[2].endswith("· running now")
    assert lines[4].endswith("· summary pending")


@pytest.mark.db
def test_twenty_sessions_with_long_names_fit_one_screen(runner, db_session):
    """M5 acceptance: `--last 5` prints at most a screenful, and so does the maximum, 20."""
    for n in range(25):
        branch = f"feature/{'very-long-branch-name-' * 4}{n}"
        stopped(db_session, f"s-{n}", n, branch=branch, files=[LONG_PATH, "b.py", "c.py"])
        pull_request(db_session, 100 + n, branch, "A long title " * 20)

    five = sessions(runner, "--repo", "shop").splitlines()
    twenty = sessions(runner, "--repo", "shop", "--last", "20").splitlines()

    assert len(five) == 11
    assert len(twenty) == 41
    assert max(len(line) for line in twenty) <= 120
    assert "3 files (…ule_with_a_long_name.py +2)" in twenty[2]  # the end of the path


@pytest.mark.db
def test_a_pull_request_title_can_not_break_out_of_its_line(runner, db_session):
    stopped(db_session, "s-1", 0, branch="feat/x")
    pull_request(db_session, 5, "feat/x", "Fix\n2026-01-01 00:00 UTC · fake entry\x1b[2J")

    output = sessions(runner, "--repo", "shop")

    assert len(output.splitlines()) == 3
    assert "\x1b" not in output


@pytest.mark.db
def test_the_repo_defaults_to_the_current_folder(runner, db_session, tmp_path, monkeypatch):
    stopped(db_session, "s-1", 0)
    (tmp_path / "shop").mkdir()
    monkeypatch.chdir(tmp_path / "shop")

    assert "in shop, newest first" in sessions(runner)


@pytest.mark.db
def test_an_unknown_repo_says_so(runner):
    output = sessions(runner, "--repo", "nowhere")

    assert output.strip() == "No agent sessions recorded for nowhere yet."


@pytest.mark.db
def test_json_has_every_field(runner, db_session):
    session_id = stopped(db_session, "s-1", 0)
    pull_request(db_session, 7, "feat/rate-limits", "Limits\nper connector")

    (entry,) = json.loads(sessions(runner, "--repo", "shop", "--json"))

    assert entry["id"] == session_id
    assert (entry["started_at"], entry["ended_at"]) == (
        "2026-11-16T10:00:00+00:00",
        "2026-11-16T10:38:00+00:00",
    )
    assert entry["goal"] == "Limits per connector"
    assert entry["pull_request"] == {
        "number": 7,
        "title": "Limits per connector",
        "outcome": "open",
    }
    assert entry["summary_state"] == "ready"
    assert entry["summary"]["files_touched"] == ["from-3-events.py"]
    assert entry["summary"]["tools"] == {"Edit": 3}


@pytest.mark.db
@pytest.mark.parametrize("last", ["0", "21", "five"])
def test_last_is_between_1_and_20(runner, last):
    assert runner.invoke(args=["sessions", "--repo", "shop", "--last", last]).exit_code != 0


def test_the_output_is_utf8_even_on_a_cp1252_console():
    """Run as a process whose stdout is cp1252, as on Windows: no mojibake, no crash on a "✓".

    The process has its own connection, so it can't see a test's rows; the repo name in the
    message it prints carries the characters cp1252 lacks.
    """
    env = {
        **os.environ,
        "PYTHONIOENCODING": "cp1252",
        "FLASK_SKIP_DOTENV": "1",
        "FLASK_DATABASE_URL": TEST_DATABASE_URL,
    }
    result = subprocess.run(
        [sys.executable, "-m", "flask", "--app", "flightlog", "sessions", "--repo", "café ✓"],
        env=env,
        capture_output=True,
        timeout=60,
    )

    assert result.returncode == 0, result.stderr.decode(errors="replace")
    assert result.stdout.decode("utf-8").strip() == "No agent sessions recorded for café ✓ yet."

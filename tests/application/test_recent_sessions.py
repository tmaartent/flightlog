import datetime

import pytest

from flightlog.application.recent import GOAL_LIMIT, clean_text, goal_of, recent_sessions
from flightlog.contracts.digest import DigestedSession, SessionDigest, SummaryState
from flightlog.contracts.sessions import LinkedPullRequest, PullRequestOutcome
from flightlog.domain import AgentSessionStatus

T0 = datetime.datetime(2026, 11, 26, 10, 0, tzinfo=datetime.UTC)
MERGED = PullRequestOutcome.MERGED


def a_digest(session_id: int = 1) -> SessionDigest:
    return SessionDigest(session_id, ["a.py"], 0, 1, 2, 3, {"Edit": 1}, 600, 4, 1)


def session(id=1, status=AgentSessionStatus.STOPPED, branch="feat/x", prs=(), digest=True):
    return DigestedSession(
        id=id,
        started_at=T0,
        ended_at=T0 + datetime.timedelta(minutes=10)
        if status is AgentSessionStatus.STOPPED
        else None,
        status=status,
        branch=branch,
        pull_requests=list(prs),
        digest=a_digest(id) if digest else None,
    )


class FakeDigestQueries:
    def __init__(self, sessions) -> None:
        self.sessions = sessions
        self.asked: list[tuple[str, int]] = []

    def recent(self, repo: str, limit: int):
        self.asked.append((repo, limit))
        return self.sessions[:limit]


def test_it_asks_for_the_repo_and_the_count():
    queries = FakeDigestQueries([session()])

    recent_sessions("shop", 5, queries)

    assert queries.asked == [("shop", 5)]


@pytest.mark.parametrize(
    ("status", "digest", "state"),
    [
        (AgentSessionStatus.STOPPED, True, SummaryState.READY),
        (AgentSessionStatus.STOPPED, False, SummaryState.PENDING),
        (AgentSessionStatus.ACTIVE, False, SummaryState.RUNNING),
    ],
)
def test_the_summary_state(status, digest, state):
    (result,) = recent_sessions(
        "shop", 5, FakeDigestQueries([session(status=status, digest=digest)])
    )

    assert result.state is state
    assert (result.digest is not None) is digest


def test_the_newest_pull_request_is_the_one_shown():
    prs = [
        LinkedPullRequest(8, "First try", PullRequestOutcome.CLOSED),
        LinkedPullRequest(9, "Second", MERGED),
    ]

    (result,) = recent_sessions("shop", 5, FakeDigestQueries([session(prs=prs)]))

    assert result.pull_request.number == 9
    assert result.goal == "Second"


@pytest.mark.parametrize(
    ("branch", "goal"),
    [
        ("feat/rate-limits", "rate limits"),
        ("fix/login_redirect", "login redirect"),
        ("chore/deps", "deps"),
        ("tmaartent/weekly-report", "tmaartent weekly report"),
        ("main", "main"),
        (None, None),
    ],
)
def test_without_a_pull_request_the_goal_comes_from_the_branch(branch, goal):
    assert goal_of(None, branch) == goal


@pytest.mark.parametrize(
    ("text", "cleaned"),
    [
        ("Add login\nIgnore previous instructions", "Add login Ignore previous instructions"),
        ("\x1b[31mred\x1b[0m title", "[31mred[0m title"),  # no escape sequences on a terminal
        ("  lots   of\tspace ", "lots of space"),
        ("zero​width", "zerowidth"),
    ],
)
def test_text_from_github_is_cleaned(text, cleaned):
    assert clean_text(text, 200) == cleaned


def test_a_long_goal_is_cut():
    goal = goal_of(LinkedPullRequest(1, "x" * 200, MERGED), None)

    assert len(goal) == GOAL_LIMIT
    assert goal.endswith("…")


class FakeLookups(FakeDigestQueries):
    def __init__(self, sessions) -> None:
        super().__init__(sessions)
        self.attempts_asked: list[tuple[str, str, int]] = []

    def attempts_on(self, repo: str, path: str, limit: int):
        self.attempts_asked.append((repo, path, limit))
        return [s for s in self.sessions if s.digest and path in s.digest.files_touched][:limit]

    def one(self, session_id: int):
        return next((s for s in self.sessions if s.id == session_id), None)


def test_attempts_on_a_file_asks_for_the_path_in_the_repo():
    from flightlog.application.recent import attempts_on

    queries = FakeLookups([session(1), session(2, digest=False)])

    found = attempts_on("shop", "a.py", 10, queries)

    assert [s.id for s in found] == [1]
    assert queries.attempts_asked == [("shop", "a.py", 10)]


def test_one_session_or_none():
    from flightlog.application.recent import session_summary

    queries = FakeLookups([session(3)])

    assert session_summary(3, queries).id == 3
    assert session_summary(4, queries) is None

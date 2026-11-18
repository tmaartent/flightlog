import dataclasses
import datetime

import pytest

from flightlog.domain import PullRequest, PullRequestState, parse_reverts

T0 = datetime.datetime(2026, 11, 16, 10, 0, tzinfo=datetime.UTC)
LATER = T0 + datetime.timedelta(minutes=5)

OPENED = PullRequest(repo="flightlog", number=7, branch="feat/x", title="Add x", updated_at=T0)


def snapshot(**changes) -> PullRequest:
    return dataclasses.replace(OPENED, **changes)


def test_a_newer_snapshot_wins():
    pr = snapshot()

    pr.update(snapshot(title="Add x, better", state=PullRequestState.CLOSED, updated_at=LATER))

    assert pr.title == "Add x, better"
    assert pr.state is PullRequestState.CLOSED
    assert pr.updated_at == LATER


def test_an_older_snapshot_is_ignored():
    pr = snapshot(state=PullRequestState.CLOSED, updated_at=LATER)

    pr.update(snapshot(state=PullRequestState.OPEN, updated_at=T0))

    assert pr.state is PullRequestState.CLOSED
    assert pr.updated_at == LATER


def test_merged_is_final_even_against_a_newer_snapshot():
    pr = snapshot(state=PullRequestState.MERGED, merged_at=T0)

    pr.update(snapshot(state=PullRequestState.OPEN, updated_at=LATER))

    assert pr.state is PullRequestState.MERGED
    assert pr.merged_at == T0


def test_a_late_merged_snapshot_still_counts():
    # The "closed" event of the merge arrives first, the older "merged" one after.
    pr = snapshot(title="Renamed after merge", updated_at=LATER)

    pr.update(snapshot(state=PullRequestState.MERGED, merged_at=T0, updated_at=T0))

    assert pr.state is PullRequestState.MERGED
    assert pr.merged_at == T0


def test_updating_with_the_same_snapshot_twice_changes_nothing():
    pr = snapshot()
    seen = snapshot(state=PullRequestState.MERGED, merged_at=LATER, updated_at=LATER)

    pr.update(seen)
    pr.update(seen)

    assert (pr.state, pr.merged_at, pr.updated_at) == (PullRequestState.MERGED, LATER, LATER)


def test_update_rejects_a_naive_datetime():
    with pytest.raises(ValueError):
        snapshot().update(snapshot(updated_at=datetime.datetime(2026, 11, 16, 10, 0)))


def test_update_rejects_another_pull_request():
    with pytest.raises(ValueError):
        snapshot().update(snapshot(number=8))


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ("Reverts tmaartent/flightlog#12", 12),
        ("Reverts tmaartent/flight-log.v2#3\n\nBroke the worker.", 3),
        ("This reverts commit 0cb1b1c", None),
        ("Fixes #12", None),
        ("", None),
        (None, None),
    ],
)
def test_parse_reverts_reads_githubs_revert_body(body, expected):
    assert parse_reverts(body) == expected

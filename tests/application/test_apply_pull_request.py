"""Use-case tests for keeping pull requests up to date, on the fake unit of work."""

import datetime

import pytest

from flightlog.application.apply_pull_request import apply_pull_request
from flightlog.contracts.ingest import GITHUB
from flightlog.domain import PullRequestState, RecordedEvent
from tests.application.fakes import FakeUnitOfWork
from tests.github_util import T0, pull_request_payload

NOW = T0 + datetime.timedelta(hours=1)
LATER = T0 + datetime.timedelta(minutes=5)


def deliver(uow: FakeUnitOfWork, payload: dict) -> int:
    """Store a GitHub pull_request delivery as ingest would. Returns its id."""
    event = RecordedEvent(
        source=GITHUB,
        delivery_id=f"d-{len(uow.events.events) + 1}",
        type="pull_request",
        occurred_at=T0,
        payload=payload,
    )
    return uow.events.add_if_new(event)


def test_the_first_delivery_creates_the_pull_request():
    uow = FakeUnitOfWork()
    event_id = deliver(uow, pull_request_payload(number=7, branch="feat/x", title="Add x"))

    apply_pull_request(event_id, NOW, uow)

    pr = uow.pull_requests.get("flightlog", 7)
    assert (pr.branch, pr.title, pr.state) == ("feat/x", "Add x", PullRequestState.OPEN)
    assert pr.updated_at == T0
    assert pr.reverts is None
    assert uow.events.get(event_id).processed_at == NOW


def test_a_merge_updates_the_same_pull_request():
    uow = FakeUnitOfWork()
    opened = deliver(uow, pull_request_payload())
    merged = deliver(uow, pull_request_payload(state="closed", merged_at=LATER, updated_at=LATER))

    apply_pull_request(opened, NOW, uow)
    apply_pull_request(merged, NOW, uow)

    assert len(uow.pull_requests.pull_requests) == 1
    pr = uow.pull_requests.get("flightlog", 7)
    assert pr.state is PullRequestState.MERGED
    assert pr.merged_at == LATER


def test_deliveries_in_the_wrong_order_give_the_same_pull_request():
    uow = FakeUnitOfWork()
    merged = deliver(uow, pull_request_payload(state="closed", merged_at=LATER, updated_at=LATER))
    opened = deliver(uow, pull_request_payload())

    apply_pull_request(merged, NOW, uow)
    apply_pull_request(opened, NOW, uow)

    assert uow.pull_requests.get("flightlog", 7).state is PullRequestState.MERGED


def test_closed_without_merging_is_closed():
    uow = FakeUnitOfWork()

    apply_pull_request(deliver(uow, pull_request_payload(state="closed")), NOW, uow)

    assert uow.pull_requests.get("flightlog", 7).state is PullRequestState.CLOSED


def test_a_revert_pr_records_which_pr_it_reverts():
    uow = FakeUnitOfWork()
    payload = pull_request_payload(
        number=8, branch="revert-7-feat/x", body="Reverts tmaartent/flightlog#7"
    )

    apply_pull_request(deliver(uow, payload), NOW, uow)

    assert uow.pull_requests.get("flightlog", 8).reverts == 7


def test_applying_a_delivery_twice_changes_nothing():
    uow = FakeUnitOfWork()
    event_id = deliver(uow, pull_request_payload())
    apply_pull_request(event_id, NOW, uow)

    apply_pull_request(event_id, NOW + datetime.timedelta(minutes=1), uow)

    assert uow.events.get(event_id).processed_at == NOW
    assert len(uow.pull_requests.pull_requests) == 1


def test_a_payload_without_a_pull_request_fails_so_the_job_stays_visible():
    uow = FakeUnitOfWork()
    event_id = deliver(uow, {"action": "opened"})

    with pytest.raises(KeyError):
        apply_pull_request(event_id, NOW, uow)

    assert uow.events.get(event_id).processed_at is None


def test_an_unknown_event_fails_so_the_job_is_retried():
    with pytest.raises(LookupError):
        apply_pull_request(999, NOW, FakeUnitOfWork())


def test_the_use_case_leaves_the_commit_to_the_worker():
    uow = FakeUnitOfWork()

    apply_pull_request(deliver(uow, pull_request_payload()), NOW, uow)

    assert uow.commits == 0

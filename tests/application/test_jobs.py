import pytest

from flightlog.application.jobs import BASE_DELAY, JobKind, jobs_for, retry_delay
from flightlog.contracts.ingest import CLAUDE, GITHUB


def test_retry_delay_gets_exponentially_longer_until_max_is_reached() -> None:
    delay = retry_delay(1)

    assert delay == BASE_DELAY

    delay = retry_delay(2)
    assert delay == BASE_DELAY * (2**1)

    delay = retry_delay(3)
    assert delay == BASE_DELAY * (2**2)

    delay = retry_delay(4)
    assert delay == BASE_DELAY * (2**3)

    delay = retry_delay(5)
    assert delay == BASE_DELAY * (2**4)

    delay = retry_delay(6)
    assert delay is None


@pytest.mark.parametrize(
    ("source", "event_type", "expected"),
    [
        (CLAUDE, "PostToolUse", [JobKind.APPLY_TO_SESSION]),
        (GITHUB, "pull_request", [JobKind.APPLY_PULL_REQUEST]),
        (GITHUB, "push", []),  # recorded, not processed (ADR-0009)
        (GITHUB, "workflow_run", []),
    ],
)
def test_jobs_for_picks_the_work_per_event(source, event_type, expected):
    assert jobs_for(source, event_type) == expected

import pytest

from flightlog.contracts.audit import AuditOutcome


@pytest.mark.parametrize(
    ("status", "outcome"),
    [
        (200, AuditOutcome.OK),
        (302, AuditOutcome.OK),  # Post/Redirect/Get after an admin action
        (401, AuditOutcome.DENIED),
        (403, AuditOutcome.DENIED),
        (429, AuditOutcome.LIMITED),
        (400, AuditOutcome.ERROR),
        (404, AuditOutcome.ERROR),
        (500, AuditOutcome.ERROR),
    ],
)
def test_the_outcome_is_derived_from_the_status(status, outcome):
    assert AuditOutcome.of(status) is outcome

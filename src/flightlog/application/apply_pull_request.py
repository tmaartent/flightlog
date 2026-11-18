import datetime
from typing import Any

from flightlog.application.events import unprocessed_event
from flightlog.application.ports import UnitOfWork
from flightlog.domain import PullRequest, PullRequestState, parse_reverts


def apply_pull_request(event_id: int, now: datetime.datetime, uow: UnitOfWork) -> None:
    """Keep the latest state of a pull request from a GitHub `pull_request` delivery.

    Does not commit: the worker owns the transaction (ADR-0008). Safe to run twice, and
    deliveries may arrive in any order: PullRequest.update keeps the newest snapshot.
    Sessions are not touched; they are linked to pull requests at read time (ADR-0009).

    Two workers handling the first deliveries of the same new PR can both try to add it; the
    unique constraint on (repo, number) makes one fail, and its retry then finds the PR.
    """
    event = unprocessed_event(event_id, uow)
    if event is None:
        return

    pr = read_pr(event.payload)
    existing = uow.pull_requests.get(pr.repo, pr.number)
    if existing is None:
        uow.pull_requests.add(pr)
    else:
        existing.update(pr)
    event.processed_at = now


def read_pr(payload: dict[str, Any]) -> PullRequest:
    """The pull request as this delivery describes it.

    A payload without the expected fields raises KeyError: the job fails and stays visible,
    instead of being marked processed with nothing applied.
    """
    pr = payload["pull_request"]
    if pr.get("merged_at"):
        state = PullRequestState.MERGED
    elif pr["state"] == "closed":
        state = PullRequestState.CLOSED
    else:
        state = PullRequestState.OPEN
    return PullRequest(
        repo=payload["repository"]["name"],  # the bare name, like AgentSession.repo
        number=pr["number"],
        branch=pr["head"]["ref"],
        title=pr["title"],
        updated_at=datetime.datetime.fromisoformat(pr["updated_at"]),
        state=state,
        merged_at=datetime.datetime.fromisoformat(pr["merged_at"]) if pr.get("merged_at") else None,
        reverts=parse_reverts(pr.get("body")),
    )

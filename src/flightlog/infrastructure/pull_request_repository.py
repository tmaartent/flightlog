from sqlalchemy import select
from sqlalchemy.orm import Session

from flightlog.domain import PullRequest


class SqlPullRequestRepository:
    """PullRequestRepository on PostgreSQL. Loaded PRs are tracked, so changes save on commit."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, repo: str, number: int) -> PullRequest | None:
        statement = select(PullRequest).filter_by(repo=repo, number=number)
        return self._session.scalars(statement).one_or_none()

    def add(self, pull_request: PullRequest) -> None:
        self._session.add(pull_request)

from sqlalchemy import and_, exists, select
from sqlalchemy.orm import Session, aliased

from flightlog.contracts.sessions import LinkedPullRequest, PullRequestOutcome
from flightlog.domain import PullRequestState
from flightlog.infrastructure.tables import agent_sessions, pull_requests


class SqlAgentSessionQueries:
    """AgentSessionQueries on PostgreSQL: plain SELECTs on the tables, no domain objects."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def linked_pull_requests(self, session_id: int) -> list[LinkedPullRequest]:
        pr = pull_requests
        revert = aliased(pull_requests)
        # Derived on read (ADR-0009): a revert that is still open has undone nothing yet.
        reverted = exists().where(
            revert.c.repo == pr.c.repo,
            revert.c.reverts == pr.c.number,
            revert.c.state == PullRequestState.MERGED,
        )
        statement = (
            select(pr.c.number, pr.c.title, pr.c.state, reverted.label("reverted"))
            .join_from(
                agent_sessions,
                pr,
                and_(pr.c.repo == agent_sessions.c.repo, pr.c.branch == agent_sessions.c.branch),
            )
            .where(agent_sessions.c.id == session_id)
            .order_by(pr.c.number)
        )
        return [
            LinkedPullRequest(
                number=row.number,
                title=row.title,
                outcome=(
                    PullRequestOutcome.REVERTED
                    if row.state is PullRequestState.MERGED and row.reverted
                    else PullRequestOutcome(row.state.value)
                ),
            )
            for row in self._session.execute(statement)
        ]

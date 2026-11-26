"""`flask summaries rebuild`: queue a summary for every stopped session that lacks a current one.

For sessions that ended before summaries existed, and after a RULES_VERSION bump (ADR-0018).
The worker does the work; this only queues it, so it is quick and safe to run twice.
"""

import click
from flask import Blueprint, current_app

from flightlog.application.digest import RULES_VERSION, rebuild_digests
from flightlog.application.ports import UnitOfWork

bp = Blueprint("summaries", __name__)  # the CLI group is named after the blueprint


@bp.cli.command("rebuild")
def rebuild() -> None:
    """Queue summarize jobs for stopped sessions without a summary of the current rules."""
    uow: UnitOfWork = current_app.extensions["unit_of_work"]()
    queued = rebuild_digests(uow)
    click.echo(
        f"Queued {queued} session summar{'y' if queued == 1 else 'ies'} (rules v{RULES_VERSION})."
    )

"""`flask connector create|list|revoke`: API keys for the read API (ADR-0005).

The key is printed once, at creation. After that only its prefix exists outside the client.
"""

import datetime

import click
from flask import Blueprint, current_app

from flightlog.application.api_keys import ConnectorNameTaken, issue_key, revoke_key
from flightlog.application.ports import ConnectorQueries, UnitOfWork
from flightlog.contracts.connectors import RevokeOutcome

bp = Blueprint("connector", __name__)  # the CLI group is named after the blueprint


def unit_of_work() -> UnitOfWork:
    return current_app.extensions["unit_of_work"]()


def now() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


def masked(prefix: str) -> str:
    """How a key is shown after creation: enough to recognise it, nothing to use."""
    return f"fl_{prefix}_…"


@bp.cli.command("create")
@click.argument("name")
def create(name: str) -> None:
    """Create a connector NAME and print its API key. The key is shown only this once."""
    try:
        issued = issue_key(name, unit_of_work(), now())
    except ConnectorNameTaken as error:
        raise click.ClickException(f"{error}; pick another name.") from None
    except ValueError as error:
        raise click.ClickException(str(error)) from None
    click.echo(f"Created connector {issued.name!r}. Its API key, shown only this once:")
    click.echo()
    click.echo(f"  {issued.key}")
    click.echo()
    click.echo("Send it as: Authorization: Bearer <key>")


@bp.cli.command("list")
def list_connectors() -> None:
    """List connectors with their key prefix and state. Never the keys themselves."""
    queries: ConnectorQueries = current_app.extensions["connector_queries"]()
    rows = queries.list_connectors()
    if not rows:
        click.echo("No connectors yet. Create one with: flask connector create <name>")
        return
    width = max(len(c.name) for c in rows)
    for c in rows:
        state = f"revoked {c.revoked_at:%Y-%m-%d %H:%M}" if c.revoked_at else "active"
        click.echo(f"{c.name:<{width}}  {masked(c.prefix)}  {c.created_at:%Y-%m-%d}  {state}")


@bp.cli.command("revoke")
@click.argument("name")
def revoke(name: str) -> None:
    """Revoke connector NAME's key. Its next request gets a 401."""
    outcome = revoke_key(name, unit_of_work(), now())
    if outcome is RevokeOutcome.NOT_FOUND:
        raise click.ClickException(f"No connector named {name!r}.")
    if outcome is RevokeOutcome.ALREADY_REVOKED:
        click.echo(f"Connector {name!r} was already revoked.")
    else:
        click.echo(f"Revoked connector {name!r}.")

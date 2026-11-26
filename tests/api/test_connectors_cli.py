"""`flask connector create|list|revoke` and the read-only /admin/connectors page (ADR-0005)."""

import re

import pytest
from sqlalchemy import select

from flightlog.infrastructure.tables import connectors

KEY = re.compile(r"fl_[0-9a-f]{8}_[A-Za-z0-9_-]{43}")


def create(runner, name: str = "ci-script") -> str:
    result = runner.invoke(args=["connector", "create", name])
    assert result.exit_code == 0, result.output
    return KEY.search(result.output).group()


@pytest.mark.db
def test_create_prints_the_key_once_and_stores_only_its_hash(runner, client, db_session):
    key = create(runner)

    row = db_session.execute(select(connectors)).one()
    assert key.startswith(f"fl_{row.key_prefix}_")
    assert key not in row
    headers = {"Authorization": f"Bearer {key}"}
    assert client.get("/api/v1/sessions", headers=headers).status_code == 200
    assert runner.invoke(args=["connector", "list"]).output.count(key) == 0


@pytest.mark.db
def test_a_name_can_not_be_used_twice(runner):
    create(runner)

    result = runner.invoke(args=["connector", "create", "ci-script"])

    assert result.exit_code != 0
    assert "exists already" in result.output


@pytest.mark.db
def test_list_shows_name_prefix_and_state(runner):
    key = create(runner, "one")
    create(runner, "two")
    runner.invoke(args=["connector", "revoke", "one"])

    output = runner.invoke(args=["connector", "list"]).output

    prefix = key.split("_")[1]
    assert re.search(rf"one\s+fl_{prefix}_…\s+.*revoked", output)
    assert re.search(r"two\s+fl_[0-9a-f]{8}_…\s+.*active", output)


@pytest.mark.db
def test_revoke_stops_the_key(runner, client):
    key = create(runner)

    result = runner.invoke(args=["connector", "revoke", "ci-script"])

    assert result.exit_code == 0
    assert "Revoked" in result.output
    headers = {"Authorization": f"Bearer {key}"}
    assert client.get("/api/v1/sessions", headers=headers).status_code == 401


@pytest.mark.db
def test_revoking_twice_or_an_unknown_name(runner):
    create(runner)
    runner.invoke(args=["connector", "revoke", "ci-script"])

    again = runner.invoke(args=["connector", "revoke", "ci-script"])
    unknown = runner.invoke(args=["connector", "revoke", "nobody"])

    assert again.exit_code == 0
    assert "already revoked" in again.output
    assert unknown.exit_code != 0
    assert "No connector named 'nobody'" in unknown.output


@pytest.mark.db
def test_the_admin_page_lists_connectors_without_their_keys(runner, admin_client):
    key = create(runner)

    response = admin_client.get("/admin/connectors")

    assert response.status_code == 200
    assert "ci-script" in response.text
    assert f"fl_{key.split('_')[1]}_…" in response.text
    assert key not in response.text


@pytest.mark.db
def test_the_admin_page_needs_the_login(client):
    response = client.get("/admin/connectors")

    assert response.status_code == 302
    assert response.headers["Location"].startswith("/login")

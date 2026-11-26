"""Errors are JSON for machines (/api, /ingest) and HTML for people (everything else)."""

import pytest


@pytest.mark.db
@pytest.mark.parametrize("path", ["/api/v1/nope", "/ingest/nope"])
def test_an_unknown_machine_url_is_a_json_404(client, path):
    """No route matched, so no blueprint handler runs: the app-level handler decides."""
    response = client.get(path)

    assert response.status_code == 404
    assert response.is_json
    assert "error" in response.json


@pytest.mark.db
def test_a_refused_webhook_is_a_json_401(client):
    response = client.post("/ingest/github", data=b"{}")

    assert response.status_code == 401
    assert response.json == {"error": "Request could not be verified"}


@pytest.mark.db
def test_the_wrong_method_keeps_its_allow_header(client):
    response = client.get("/ingest/github")

    assert response.status_code == 405
    assert response.is_json
    assert "POST" in response.headers["Allow"]


@pytest.mark.db
def test_pages_for_people_keep_flasks_html_errors(client):
    response = client.get("/nope")

    assert response.status_code == 404
    assert response.mimetype == "text/html"

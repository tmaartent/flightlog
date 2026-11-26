"""A Flightlog without its webhook secrets refuses deliveries instead of accepting forgeries."""

import json
import logging

import pytest

from flightlog import create_app
from tests.harness import TEST_DATABASE_URL, make_test_app
from tests.util import make_signature


@pytest.mark.db
@pytest.mark.parametrize(
    ("path", "header", "secret_key"),
    [
        ("/ingest/github", "X-Hub-Signature-256", "GITHUB_WEBHOOK_SECRET"),
        ("/ingest/claude", "X-Flightlog-Signature", "CLAUDE_HOOK_SECRET"),
    ],
)
@pytest.mark.parametrize("secret", ["", None], ids=["empty", "unset"])
def test_a_missing_secret_refuses_even_an_empty_key_signature(
    db_connection, path, header, secret_key, secret
):
    app = make_test_app(db_connection)
    if secret is None:
        app.config.pop(secret_key)
    else:
        app.config[secret_key] = secret
    body = json.dumps({"hook": {}}).encode()

    response = app.test_client().post(
        path,
        data=body,
        content_type="application/json",
        headers={header: make_signature(body, ""), "X-GitHub-Delivery": "d", "X-GitHub-Event": "e"},
    )

    assert response.status_code == 401


def test_missing_secrets_are_named_in_a_warning_at_startup(caplog, monkeypatch):
    for name in ["GITHUB_WEBHOOK_SECRET", "CLAUDE_HOOK_SECRET", "ADMIN_PASSWORD_HASH"]:
        monkeypatch.delenv(f"FLASK_{name}", raising=False)  # CI sets some of these
    with caplog.at_level(logging.WARNING):
        create_app({"TESTING": True, "DATABASE_URL": TEST_DATABASE_URL, "SECRET_KEY": "x"})

    assert "GITHUB_WEBHOOK_SECRET" in caplog.text
    assert "CLAUDE_HOOK_SECRET" in caplog.text
    assert "ADMIN_PASSWORD_HASH" in caplog.text
    assert "SECRET_KEY is not set" not in caplog.text

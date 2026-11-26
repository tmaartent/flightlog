# 04 · Read API with a key per connector (M4, task 1)

Branch `feat/read-api`. Decision record: [ADR-0005](../../adr/0005-api-keys-per-connector.md), now Accepted.

## What was built
- **Connectors** (`domain/connector.py`, `application/api_keys.py`): `issue_key` makes `fl_<8 hex>_<token_urlsafe(32)>` and stores only the prefix and a SHA-256 of the key. `authenticate` finds the row by prefix and compares hashes with `hmac.compare_digest`. `revoke_key` is safe to repeat. Names are never reused.
- **Schema**: the `connectors` table with unique `name` and `key_prefix`. Migration `3f83215d2351`, drafted by autogenerate and read by hand.
- **CLI** `flask connector create|list|revoke`: the key is printed once; `list` shows `fl_<prefix>_…`.
- **Read API** (`api/read_api.py`): `GET /api/v1/sessions` (filters, keyset `next`, `limit` from 1 to 100) and `GET /api/v1/sessions/<id>` (the dashboard's timeline as JSON). Authentication in `before_request` sets `g.connector`; every failure is the same 401 with `WWW-Authenticate: Bearer`.
- **Admin page** `/admin/connectors`, read-only, linked from the nav.
- **JSON errors** for `/api/…` and `/ingest/…` through one app-level handler (`api/errors.py`). The guide described this, but it had never been built: `/ingest` errors were HTML until now.
- **Tests**: 345 in total (+59).

## What I learned
- **Werkzeug parses `Authorization` for you.** `request.authorization` is an `Authorization` object: `.type == "bearer"` (lowercased) and `.token`. For `Basic`, the token is `None` and the username and password are in `.parameters`.
- **Flask's JSON provider writes a `datetime` as an HTTP date** (`Mon, 16 Nov 2026 10:00:00 GMT`). Convert times to ISO 8601 yourself in an API.
- **An `HTTPException` is itself a response.** An error handler can return it unchanged to get Flask's HTML page, so one handler can choose JSON or HTML by path.
- **Instances made at import time aren't mapped.** A `Connector(...)` in `@pytest.mark.parametrize` is built at collection, before `start_mappers()`, so SQLAlchemy raises `UnmappedInstanceError` when it's added. Parametrize with values, not entities.
- **Why a fast hash is fine for API keys:** a slow hash protects guessable input. 256 random bits can't be guessed, so a slow hash would only make every request slower.

## Open questions
- **Revoke from the admin page:** waits for the audit log (task 3), so the admin action is recorded.
- **Key rotation with overlap** would need an `api_keys` table; not needed while each client can switch keys in one go.
- **Should `/health` answer JSON errors too?** It's outside `/api` and `/ingest`, so it gets HTML errors for now.

# 0005 · API keys per connector

- Status: Accepted
- Date: 2026-11-12, accepted 2026-11-26 (M4 task 1)

## Context
The read API is used by more than one client (a script, a dashboard elsewhere, the M5 client). One shared key can't be revoked for one client, and logs can't tell clients apart.

## Decision
Each connector gets its own key: `fl_<prefix>_<secret>`. Only a SHA-256 hash and the prefix are stored; the full key is shown once at creation. Requests send `Authorization: Bearer <key>`. Rate limits and audit rows are keyed on the connector.

Details, settled in the M4 task 1 grilling round:

- **One table, one key per connector.** `connectors(id, name unique, key_prefix unique, key_hash, created_at, revoked_at)`. Rotating a key means creating a new connector and revoking the old one. Names are never reused, not even after a revoke, so an audit row's connector always means one client. A separate `api_keys` table (1:n, so an old and a new key can overlap) waits until a client can't switch keys in one step.
- **Key shape.** The prefix is 8 hex characters (`secrets.token_hex(4)`) and the secret is `secrets.token_urlsafe(32)` (256 bits). The secret can contain `_`; the prefix can't, so a key is split on its first two underscores. The timeline's secret masking already recognises `fl_<prefix>_…` and keeps only the prefix.
- **Lookup and comparison.** The prefix finds the row; `hmac.compare_digest` compares `sha256(full key)` with the stored hash, so timing doesn't show how close a guess was. An unknown prefix fails earlier, which only reveals that the prefix doesn't exist: the prefix isn't secret.
- **Layers.** `domain.Connector` (`is_active`, `revoke(now)`, safe to repeat); the use cases `issue_key`, `authenticate` and `revoke_key` in `application/api_keys.py`; `ConnectorRepository` and `ConnectorQueries` as ports. `hashlib`, `hmac` and `secrets` are stdlib, so the application layer stays framework-free.
- **Managing keys.** `flask connector create <name>` prints the key once; `flask connector list` and `flask connector revoke <name>` do the rest. `/admin/connectors` lists name, prefix, created and state, read-only, behind the admin login. A revoke button there waits for the audit log (ADR-0014), so that admin action is recorded.
- **No `last_used_at`.** It would add a write to every read request. The audit log answers "when was this key last used".
- **Authentication in `before_request`** on the `read_api` blueprint, setting `g.connector` (a `ConnectorRef(id, name)`) for the rate limiter and the audit log. A route added later can't forget it.
- **One 401 for everything.** A missing, malformed, wrong or revoked key all get `401 {"error": "invalid or missing API key"}` with `WWW-Authenticate: Bearer realm="flightlog"`, so a caller can't tell a typo from a revoked key. The admin cookie is not accepted: the API reads no cookies, so it needs no CSRF check.

The read API itself:

- `GET /api/v1/sessions?repo=&status=&after=&limit=` returns `{"sessions": [...], "next": <cursor> | null}`. It uses the dashboard's `parse_session_filter` and keyset cursor. `limit` defaults to 25 and has a maximum of 100; anything else is a 400.
- `GET /api/v1/sessions/<id>` returns `{"session", "pull_requests", "files_touched", "test_runs", "entries"}`: the same `SessionTimeline` the dashboard shows, with commands masked and never a raw payload.
- JSON is written by hand in `api/read_api.py`, not with marshmallow or pydantic: the JSON is a public contract and shouldn't change when a dataclass field is renamed. Times are ISO 8601 in UTC.
- Errors on `/api/…` and `/ingest/…` are JSON through one app-level handler (`api/errors.py`), also for URLs that match no route.

## Consequences
- One leaked key is revoked without touching the others.
- A plain SHA-256 is fine here because the keys are long and random; passwords would need a slow hash.
- A lost key can't be recovered, only replaced by a new connector.
- Every API request costs one indexed lookup on `key_prefix` before the query it asked for.
- Key rotation without downtime needs two connectors for a while; audit rows then show two names for one client.

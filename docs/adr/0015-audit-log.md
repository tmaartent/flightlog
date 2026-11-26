# 0015 · An audit log written after every audited request

- Status: Accepted
- Date: 2026-11-26
- Builds on: [ADR-0005](0005-api-keys-per-connector.md), [ADR-0012](0012-admin-login-and-csrf-tokens.md), [ADR-0014](0014-rate-limits-per-connector.md)

## Context
M4 task 3: who (connector), what (route, method), which object, when and with what outcome, for every read API call and every admin action. The plan's acceptance criterion: every API call leaves one audit row. Refused requests (401, 429) matter most for security, and they never reach a use case.

## Decision
- **One mechanism: an app-level `after_request`** (`api/audit.py`) writes one row through the `AuditLog` port. It runs after the response is built, so it sees the final status, including a 401 from a `before_request`, an error handler's page and a 429 from the rate limiter. Rejected: rows written by the use cases in their own transaction. Reads and refusals have no use case, so that would mean two mechanisms.
- **What is audited:**
  - every request whose path starts with `/api/`, matched or not;
  - every POST, PUT, PATCH or DELETE on `auth`, `admin` and `dashboard`: login (success and failure), logout, retry and revoke.

  Not dashboard GETs, and not `/ingest`: the event log already keeps every delivery.
- **Columns:**

  | Column | Content |
  | --- | --- |
  | `occurred_at` | the database clock |
  | `actor_kind` | `connector`, `admin` or `anonymous` |
  | `connector_id` | FK to `connectors` |
  | `ip` | the client's address |
  | `method` | e.g. `GET` |
  | `endpoint` | the Flask endpoint, stable when a URL changes; NULL when no route matched |
  | `path` | the URL asked for, without the query string |
  | `object_type`, `object_id` | what the request is about, when there is one object |
  | `status` | the HTTP status |

  The **outcome is derived from `status`, never stored:** below 400 is ok (a 302 is Post/Redirect/Get), 401 and 403 are denied, 429 is limited, the rest is error. Ids are `BIGINT`, because a flood of 429s is one row each.
- **The actor.** For `/api` it is the connector from `current_connector()`, the lookup the rate limiter already cached on `g`. For admin actions it is `admin` if the session was admin before the request *or* is admin after it. Logout clears the session and login sets it, so only both checks together are right for both.
- **The object is declared by the view:** `audit_object("session", session_id)`, `("job", job_id)` and `("connector", connector_id)`, called before the lookup so a 404 still names the id. Rejected: guessing it from `view_args`, which silently breaks on a new parameter name.
- **Its own transaction, fail-open.** `SqlAuditLog` writes on a fresh session and commits at once. The request session is closed first: the response is built, and a request then holds one pooled connection at a time, not two. If the write fails, the error is logged and the response still goes out. The cost: an outage of the audit log means unaudited requests, and a crash between retry's commit and its audit row leaves an unaudited retry. Fail-closed (a 500 instead) was the alternative. It is stricter, but an audit outage would take the API down with it.
- **Append-only.** The port has only `record()`; nothing updates or deletes rows. Database privileges aren't restricted (yet).
- **The IP is stored.** It is personal data, kept for security (legitimate interest), and needed to follow up anonymous 401s. Behind a proxy it is the proxy's address until `ProxyFix` (task 6).
- **An anonymous POST to an admin route is now a 401**, no longer a redirect to `/login`. A redirect would drop the POST anyway, and its 302 would read as "ok" in the log. GETs still redirect.
- **Admin pages:** `/admin/audit` lists the newest 100 rows, with filters on connector and outcome and keyset paging on the id. `/admin/connectors` now has a Revoke button (POST with CSRF, Post/Redirect/Get).

## Consequences
- Every audited request costs one INSERT and one commit.
- The table only grows. Retention (`flask audit prune --older-than 90d`) or sampling of 429s waits until the size matters.
- **Tests need every app on the test transaction.** An app on the real engine commits its audit rows for good: an audited login test left rows behind until all test apps went through `tests.harness.make_test_app`.
- In tests the request session and the audit session share one connection, so their SAVEPOINTs nest. Closing the request session before the audit write is what keeps the audit row from being rolled back with the request's savepoint.

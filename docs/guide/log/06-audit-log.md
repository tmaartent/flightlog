# 06 · Audit log (M4, task 3)

Branch `feat/audit-log`. Decision record: [ADR-0015](../../adr/0015-audit-log.md).

## What was built
- **`audit_log` table** (migration `8fba016aa79c`): actor, connector, IP, method, endpoint, path, object and status. The outcome is derived from the status when the log is read.
- **`api/audit.py`**: an app-level `after_request` that writes one row for every `/api/…` request and every unsafe method on `auth`, `admin` and `dashboard`. Views name their object with `audit_object(...)`. It is fail-open: a failed write is logged and the response still goes out.
- **`SqlAuditLog`** writes on its own session and commits at once. **`SqlAuditQueries`** lists rows newest first, filtered by connector or outcome, paged on the id.
- **`api/bearer.py`**: `current_connector()` moved out of `read_api`, because the read API, the rate limiter and the audit log all need it.
- **Admin pages**: `/admin/audit`, and a Revoke button on `/admin/connectors` (`revoke_connector` by id).
- **Behaviour change**: an anonymous POST to an admin route is a 401 instead of a redirect to `/login`.
- **Tests**: 392 in total (+37). All test apps now go through `tests.harness.make_test_app`.

## What I learned
- **`after_request` sees everything.** It runs for responses returned by `before_request`, for error handlers' responses, and for unhandled errors turned into a 500, except when Flask lets exceptions propagate (`TESTING`, debug mode). That makes it the one place that knows the final status.
- **Session state changes during the request.** Login sets the admin flag and logout clears it, so "who" is the state before *or* after the request. A `before_request` remembers the "before".
- **Nested SAVEPOINTs in tests.** Two sessions on one connection with `join_transaction_mode="create_savepoint"` nest their savepoints. A read-only request left its savepoint open, the audit row went inside it, and the teardown rollback removed the row. Closing the request session first fixed the test, and in production a request now holds one pooled connection at a time instead of two.
- **A test app on the real engine leaks.** One login test used `make_app()` without the test transaction, and its audited login committed rows that broke later tests. The fix was one helper that every test app goes through.
- **Fail-open or fail-closed is an availability and integrity trade-off.** Here a broken audit log must not take the API down, so the error is logged instead.

## Open questions
- **Retention:** prune old rows with a CLI command once the table grows.
- **Unaudited retry after a crash:** retry commits before its audit row. If that ever matters, write the row in the use case's transaction for admin actions.
- **Database privileges:** a role without UPDATE or DELETE on `audit_log` would make append-only a database guarantee, not just a code convention.

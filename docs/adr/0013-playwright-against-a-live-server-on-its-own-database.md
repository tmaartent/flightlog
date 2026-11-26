# 0013 · Playwright against a live server on its own database

- Status: Accepted
- Date: 2026-11-26

## Context
ADR-0006 picked Playwright for browser tests. A browser needs a real HTTP server, but every other database test runs inside one transaction on one connection that is rolled back afterwards (`tests/conftest.py`). A live server answers on its own threads, and a SQLAlchemy connection must not be shared between threads, so the browser can't see a test's uncommitted rows.

The tests must also stay honest about how data arrives: in production it comes in as signed deliveries and is applied by the worker, not inserted into tables.

## Decision
- **A threaded Werkzeug server in the test process.** A session-scoped `live_server` fixture runs `werkzeug.serving.make_server("127.0.0.1", 0, app, threaded=True)` in a daemon thread. Port 0 lets the OS pick a free port. pytest-playwright's `base_url` fixture is overridden to point at it, so tests write `page.goto("/sessions")`.
- **Its own database, `flightlog_e2e`,** migrated to head once per run and emptied with `TRUNCATE … RESTART IDENTITY` before each test. It is separate from `flightlog_test`, so a browser test can't leave rows behind for the transactional tests, or the other way round.
- **Seeded through the front door.** `tests/e2e/flows.py` posts hook events signed by the hook client's own `build_request`, and GitHub deliveries signed like GitHub signs them, through the app's test client. Then it runs `flask worker --once`. There's no raw SQL apart from the truncate.
- **What Playwright tests:** user journeys (list, filters, paging, timeline, PR outcome, the pending notice; later login and retry, and the full M4 flow). The rules (escaping, masking, 400s, CSRF rejection) stay in fast Flask test-client tests.
- **Selectors:** role and label first (`get_by_role`, `get_by_label`), so the tests double as a check that the pages are accessible. `data-testid` only where an element has no accessible name.
- Every test under `tests/e2e/` is marked `e2e` and `db` automatically, and CI runs them with the rest.

Alternatives considered: `flask run` in a subprocess (slower to start, its output is lost on failure, and config has to go through environment variables); running against `docker compose` (right for one smoke test in M4, too slow for every UI test); and sharing the test connection with the server thread (breaks SQLAlchemy's one-connection-per-thread rule).

## Consequences
- A UI test costs about one second; the suite stays quick enough to run on every change.
- Tests can't run in parallel against the one e2e database (pytest-xdist would need a database per worker).
- The live server shares the app object with the test, so a test can change `app.config` (through the `app_config` fixture, which restores it).
- Seeding through ingest and the worker makes each UI test an integration test of ingest as well. A failure can come from either side; the transactional tests narrow it down.

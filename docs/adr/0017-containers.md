# 0017 · Containers: two images, a migrate service, Redis, and a compose smoke test

- Status: Accepted
- Date: 2026-11-26
- Builds on: [ADR-0006](0006-playwright-for-e2e-and-pdf.md), [ADR-0014](0014-rate-limits-per-connector.md), [ADR-0016](0016-weekly-report.md)

## Context
M4 task 6: a `Dockerfile`, and app and worker services in `docker-compose.yml`. Acceptance: "`docker compose up` runs the whole stack; CI is green". Until now compose ran only PostgreSQL. ADR-0014 left two open points for this task: rate-limit counters were per process, and per-IP limits assumed nothing sits in front of the app.

## Decision
- **One `Dockerfile`, three stages.**
  - `builder` builds every wheel.
  - `runtime` (`python:3.13-slim`) installs them, carries `alembic.ini` and `migrations/`, runs as `flightlog` (uid 10001), and serves with **gunicorn** (`--workers 2 --threads 4`, access log to stdout). It is used by app, worker and migrate.
  - `report` adds headless Chromium (`playwright install --with-deps --only-shell chromium`, into `/ms-playwright`, after `libatomic1`, which Playwright's own Node needs to start). Its entrypoint is `flask report`.

  Measured sizes: runtime 489 MB, report 1.4 GB. Only `flask report` pays for the browser.
- **Compose services:**

  | Service | What it does |
  | --- | --- |
  | `db` | PostgreSQL, as before |
  | `redis` | the rate-limit counters (`FLASK_RATELIMIT_STORAGE_URI=redis://redis:6379/0`, the `redis` extra of Flask-Limiter) |
  | `migrate` | `alembic upgrade head`, once per `up`; the other services wait for it with `condition: service_completed_successfully` |
  | `app` | gunicorn on `${FLIGHTLOG_APP_PORT:-8000}`, with a healthcheck through `python -c` (the slim image has no curl) |
  | `worker` | `flask worker`, with `stop_grace_period: 30s`; SIGTERM ends it between jobs, exit 0 |
  | `report` | in the `tools` profile: `docker compose run --rm report --week 2026-W46` writes to `./reports` |

  Migrations in the app's entrypoint would race once there is more than one app container.
- **Config:** the services set `FLASK_DATABASE_URL` and the Redis URL themselves. Secrets come from the shell or the project's `.env` through `${VAR:-}`.
  - **Changed during the build** (grilling round: `${VAR:?}`). Compose interpolates the whole file, so `:?` broke every compose command, `docker compose up -d db` included, whenever one secret was missing.
  - Instead, the app **logs a warning per missing secret at startup** and refuses what that secret protects.
  - Compose reads an unquoted `$` in `.env` as a variable, so the scrypt hash goes in single quotes (`.env.example` says so).
- **An empty webhook secret refuses everything.** `verify()` used to accept a delivery signed with an empty key when the configured secret was empty. Anyone can compute that HMAC. Found while choosing compose defaults; now an empty or missing secret is a 401.
- **ProxyFix only on request.** `FLASK_PROXY_COUNT` (default 0) wraps the app in `ProxyFix(x_for=n, x_proto=n)`. Without a proxy, `X-Forwarded-For` is set by the client, and trusting it would let anyone choose their IP and get round the per-IP limits (a test proves they can't). Compose leaves it at 0.
- **Host ports are variables** (`FLIGHTLOG_DB_PORT`, `FLIGHTLOG_APP_PORT`). A second copy of the stack, `-p flightlog-smoke`, then runs next to the developer's database without touching it.
- **"CI is green" with the stack.** A `compose` CI job builds both images, runs `docker compose up -d --build --wait` and `pytest -m compose` (`tests/compose/test_smoke.py`), then renders one report in the report container. The smoke test:
  - checks that `/health` reports the database as ok;
  - sends `SessionStart` and `SessionEnd` through the real hook script;
  - creates a key with `docker compose exec app flask connector create`;
  - polls the read API until the worker *service* has applied the session;
  - checks that the rate-limit counter is in Redis.

  It is skipped unless `E2E_COMPOSE_URL` is set. The browser journeys are not repeated against the containers.

## Consequences
- `docker compose up -d --build --wait` runs the whole stack on port 8000. `docker compose up -d db` still runs only the database for development and tests.
- Rate limits now hold across gunicorn's workers and restarts. Without the Redis service (outside compose), `memory://` is still the default.
- On a Linux host the bind-mounted `./reports` must be writable by uid 10001 (CI uses `mkdir -m 777 reports`). Docker Desktop doesn't need that.
- Behind a TLS proxy: set `FLASK_PROXY_COUNT`, and leave out `FLASK_SESSION_COOKIE_SECURE=false`, so the admin cookie is `Secure` again.
- The report image takes the longest to build in CI (a few minutes for Chromium and its libraries).

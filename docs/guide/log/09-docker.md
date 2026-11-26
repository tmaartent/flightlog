# 09 · Docker: the whole stack in compose (M4, task 6)

Branch `feat/docker`. Decision record: [ADR-0017](../../adr/0017-containers.md).

## What was built
- **`Dockerfile`** with `builder`, `runtime` (gunicorn, non-root, migrations included) and `report` (headless Chromium) stages, plus a `.dockerignore`.
- **`docker-compose.yml`**: `db`, `redis`, `migrate`, `app`, `worker`, and `report` in the `tools` profile. Host ports are configurable.
- **gunicorn** and the **`redis` extra of Flask-Limiter** as dependencies.
- **ProxyFix behind `FLASK_PROXY_COUNT`**, off by default.
- **Missing secrets** are logged at startup, and an **empty webhook secret now refuses every delivery** (it used to accept signatures made with an empty key).
- **`tests/compose/test_smoke.py`** (marked `compose`), and a `compose` CI job that builds, starts, smoke-tests and renders a report.
- **Tests**: 444 in total (+12), 2 of them skipped without a running stack.

Checked by hand on a second stack (`-p flightlog-smoke`, ports 5434 and 8001):
- migrations from an empty database;
- `up --wait` until every service was healthy;
- the smoke test, including the Redis key `LIMITS:{LIMITER/connector:1/read_api/120/1/minute}`;
- `docker compose run --rm report --week 2026-W48`, which gave a 1-page PDF;
- `docker compose stop worker`: "Received signal 15, shutting down gracefully", exit 0.

## What I learned
- **Compose interpolates the whole file.** A required variable (`${VAR:?}`) in the app service also breaks `docker compose up -d db`.
- **Compose expands `$` in `.env` values,** so a scrypt hash is silently cut short unless it is single-quoted.
- **An HMAC with an empty key is still an HMAC.** "Secret not configured" must mean "refuse", or any client can sign.
- **`X-Forwarded-For` is client input** unless a proxy you control overwrites it. ProxyFix is a trust decision, so its default is off.
- **Playwright's Node needs `libatomic1`** on `python:3.13-slim` before `playwright install --with-deps` can run. `--only-shell` installs only the headless shell, which is all `page.pdf()` needs.
- **The exec form of `CMD`** (a JSON list) makes gunicorn PID 1, so `docker stop`'s SIGTERM reaches it directly.

## Open questions
- **Image size:** the runtime image still installs the Playwright package (its Node driver), because it is a main dependency. A `report` extra would make runtime smaller.
- **Scheduling the report:** a cron container or the host's cron calling `docker compose run --rm report`.
- **A reverse proxy with TLS** in compose (Caddy or Traefik), with `FLASK_PROXY_COUNT=1`, for a real deployment.

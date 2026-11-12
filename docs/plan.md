# Plan

Four milestones, each small enough for one evening. Each acceptance criterion is a test you write first.

## M1 · Skeleton: Flask, PostgreSQL, Alembic

Goal: an app that starts, talks to PostgreSQL and has its first migration.

Tasks
1. `src/flightlog/__init__.py` with `create_app(config=None)`: loads `.env`, reads `DATABASE_URL`, registers blueprints, registers error handlers that return JSON for `/ingest` and `/api`.
2. `db.py`: a SQLAlchemy `Engine` and `sessionmaker`, one session per request (open on first use, close in `teardown_appcontext`). See [ADR-0002](adr/0002-plain-sqlalchemy-with-a-session-per-request.md).
3. Models: `AgentSession` (id, source, external id, repo, branch, status, started_at, ended_at) and `Event` (id, source, delivery id, type, occurred_at, received_at, payload JSONB, processed_at).
4. `alembic init migrations`, point `env.py` at `DATABASE_URL` and your metadata, then write migration 0001 and read it line by line before applying.
5. `GET /health` returns `{"status": "ok", "db": "ok"}` after a `SELECT 1`.

Done when
- [ ] `pytest` runs a test against a `create_app` with a test config, and a `db`-marked test against the compose PostgreSQL
- [ ] `alembic upgrade head` and `alembic downgrade base` both work
- [ ] `flask --app flightlog run --debug` serves `/health`

## M2 · Ingest: signed, idempotent, out of order

Goal: events from Claude Code and GitHub land safely, exactly once. See [ADR-0003](adr/0003-store-then-acknowledge.md) and [ADR-0004](adr/0004-idempotency-and-ordering.md).

Tasks
1. `ingest` blueprint: `POST /ingest/github` and `POST /ingest/claude`.
2. Signature check: GitHub sends `X-Hub-Signature-256: sha256=<hex>` over the **raw body**. Compute HMAC-SHA256 with the secret, compare with `hmac.compare_digest`. Same scheme for the Claude hook client, with your own header (`X-Flightlog-Signature`).
3. Store the raw event with a **unique constraint on (source, delivery_id)**; a duplicate returns 200 without a second row. GitHub's delivery id is `X-GitHub-Delivery`; the hook client sends a UUID it generates.
4. Return **202** right after storing. No processing in the request.
5. `scripts/flightlog_hook.py`: reads the hook JSON from stdin, signs it, POSTs it, never blocks the agent (short timeout, always exit 0). Wire it into `.claude/settings.json` for `SessionStart`, `PostToolUse` and `Stop`. Check the hook input format in the Claude Code docs for your installed version.
6. A worker (`flask --app flightlog worker`, a click command) that claims unprocessed events with `SELECT … FOR UPDATE SKIP LOCKED`, applies them to `AgentSession`, and marks them processed.

Done when
- [ ] Bad or missing signature → 401, nothing stored
- [ ] The same delivery twice → one row, both requests succeed
- [ ] `Stop` processed before the last `PostToolUse` → the session still ends as `stopped` with all its tool calls
- [ ] Two workers running at once never process the same event twice (an integration test with two connections)
- [ ] A failing event is retried with backoff, and after N attempts marked `failed` with the error

## M3 · Link and show

Goal: see what an agent did and what came of it.

Tasks
1. GitHub `pull_request` and `push` events: link a session to a PR through the branch name (the hook payload carries `cwd`; read the branch from it in the hook client).
2. `dashboard` blueprint with Jinja templates: a session list (filter by repo, status) and a timeline per session: tool calls, files touched, test runs, the linked PR and its outcome.
3. `failed` events visible on an admin page, with a "retry" button (POST, not GET).

Done when
- [ ] A session with a merged PR shows the PR and "merged"; a reverted PR shows "reverted"
- [ ] The retry button re-queues a failed event, and the test proves it is processed

## M4 · Secure API, Playwright, Docker

Goal: production manners.

Tasks
1. `api` blueprint: `GET /api/v1/sessions` and `GET /api/v1/sessions/<id>`. Bearer API key **per connector**, stored as a SHA-256 hash with a prefix you can show in the UI. See [ADR-0005](adr/0005-api-keys-per-connector.md).
2. Rate limiting with Flask-Limiter, keyed on the connector, not the IP.
3. Audit log table: who (connector), what (route, method), which object, when, outcome. Written for every API call and every admin action.
4. Weekly report: a Jinja template rendered to PDF with Playwright's `page.pdf()` in headless Chromium (`flask --app flightlog report --week 2026-W46`). See [ADR-0006](adr/0006-playwright-for-e2e-and-pdf.md).
5. Playwright end-to-end test: start the app, post a signed event, run the worker once, open the dashboard and assert the session appears.
6. `Dockerfile` and app + worker services in `docker-compose.yml`.

Done when
- [ ] No key, wrong key or revoked key → 401; over the limit → 429 with `Retry-After`
- [ ] Every API call leaves one audit row
- [ ] The report PDF exists and has one page per repo
- [ ] `docker compose up` runs the whole stack; CI is green

## Later (only if there's time)

- A short summary per session from the Claude API: what the session tried and whether it worked, as structured output.
- Alerts when an agent edits files you marked as sensitive.

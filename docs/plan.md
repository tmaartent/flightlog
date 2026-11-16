# Plan

Four milestones, each small enough for one evening. Each acceptance criterion is a test you write first.

## M1 · Skeleton: Flask, PostgreSQL, Alembic

Goal: an app that starts, talks to PostgreSQL and has its first migration.

Tasks
1. `src/flightlog/__init__.py` with `create_app(config=None)`: loads `.env`, reads `DATABASE_URL`, registers blueprints, registers error handlers that return JSON for `/ingest` and `/api`.
2. `db.py`: a SQLAlchemy `Engine` and `sessionmaker`, one session per request (open on first use, close in `teardown_appcontext`). See [ADR-0002](adr/0002-plain-sqlalchemy-with-a-session-per-request.md).
3. Models: `AgentSession` (id, source, external id, repo, branch, status, started_at, ended_at) and `Event` (id, source, delivery id, type, occurred_at, received_at, payload JSONB, processed_at).
4. `alembic init migrations`, point `../migrations/env.py` at `DATABASE_URL` and your metadata, then write migration 0001 and read it line by line before applying.
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
6. A worker (`flask --app flightlog worker`, a click command, `--once` for tests) that claims queued jobs with `SELECT … FOR UPDATE SKIP LOCKED`, applies their event to `AgentSession`, and deletes the job ([ADR-0008](adr/0008-job-table-deleted-on-success.md)).

Done when
- [x] Bad or missing signature → 401, nothing stored
- [x] The same delivery twice → one row, both requests succeed
- [x] `SessionEnd` processed before earlier events → the session still ends as `stopped`, starting at its first event
- [x] Two workers running at once never claim the same job (an integration test with two connections)
- [x] A failing job is retried with backoff, and after 5 attempts marked failed with the error

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

## M5 · Agent in the loop

Goal: a new agent session starts with a short history of what was tried before, instead of from scratch. Flightlog keeps humans in the loop; this keeps the agent in the loop too, without polluting its context.

The value is in the summaries, not the protocol: an MCP server that passes raw events through adds noise instead of preventing it. So summaries come first, a CLI second, MCP last.

Tasks
1. A summary per session, as structured data: goal, files touched, test runs, outcome (PR merged, reverted, none). Optionally a short text from the Claude API as structured output. Stored, so it's computed once.
2. `flask --app flightlog sessions --repo <name> --last 5`: a compact summary any agent can already call through its shell, with no extra server.
3. A read-only MCP server as another adapter in the `api` layer, calling the same application queries as the read API (M4). Three tools, no more:
    - `recent_sessions(repo)`: date, goal, files touched, outcome
    - `attempts_on(path)`: earlier sessions that touched this file, and what came of them
    - `session_summary(id)`: the stored summary of one session

Rules
- **Structured output only** (counts, paths, outcomes, ids). Never raw transcript or tool text: old sessions contain content from web pages and files, and feeding that back would bring injected instructions back with it.
- **Filter its own events:** calls to `mcp__flightlog__*` trigger `PostToolUse` hooks; don't record them, or Flightlog logs itself.
- **Read-only and local.** Tool inputs can contain secrets; summaries leave them out.
- Small answers: a tool result fits on one screen.

Done when
- [ ] Every finished session has a stored summary; a test checks it holds no raw tool input
- [ ] `sessions --last 5` prints at most a screenful
- [ ] A new Claude Code session can call `recent_sessions` and gets structured data back
- [ ] Calls to the Flightlog MCP tools don't show up as events in Flightlog
- [ ] The MCP server imports nothing from `infrastructure` (import-linter)

## Later (only if there's time)

- Alerts when an agent edits files you marked as sensitive.

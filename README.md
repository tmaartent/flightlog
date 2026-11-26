# Flightlog

**A flight recorder for coding agents.** Flightlog records what your Claude Code sessions do: every tool call, file edit and test run. It links each session to the branch and pull request it produced, and tracks whether that PR was merged, closed or later reverted. You get a dashboard, a weekly PDF report, a secure read API, and an MCP server that gives the *next* agent session a short, safe history of what was tried before.

![The session list: every agent session, its repo, branch, status and duration](docs/images/sessions.png)

```
Claude Code hooks ──► hook script (HMAC-signed) ──┐
GitHub webhooks (pull_request) ───────────────────┴──► POST /ingest/<source>
                                                         verify · store once · 202
                                                              │
                                     job queue (PostgreSQL, SKIP LOCKED, retries)
                                                              │
                         worker: apply to session · link PRs · compute summaries
                                                              │
        ┌──────────────┬──────────────┬─────────────────┬─────┴──────────┬───────────────┐
    dashboard    weekly PDF     read API (keys,   flask sessions   MCP server   Python client
    + timeline     report      limits, audit)    (agent's shell)   (3 tools)    (scripts)
```

---

## Contents

- [Why Flightlog](#why-flightlog)
- [The best features](#the-best-features)
- [A tour of the UI](#a-tour-of-the-ui)
- [Keeping the agent in the loop](#keeping-the-agent-in-the-loop)
- [How it works](#how-it-works)
- [Security model](#security-model)
- [Getting started](#getting-started)
- [Configuration](#configuration)
- [Command reference](#command-reference)
- [Project layout and engineering](#project-layout-and-engineering)
- [Further reading](#further-reading)

---

## Why Flightlog

Coding agents are fast, and it is easy to lose track of what they did. A session edits a dozen files, runs the tests, opens a PR, and is gone. A week later nobody remembers which session produced which change, whether its tests passed, or that the same file was reverted twice before.

Flightlog answers those questions:

| Question | Where the answer is |
| --- | --- |
| What did the agent actually do in that session? | The session's **timeline**: every edit, test run and tool call in order, with secrets masked |
| What came of it? | The **linked pull request** and its outcome: open, closed, merged, or **reverted** |
| What happened this week, per repo? | The **weekly PDF report**, one A4 page per repo |
| Has an agent tried this before, and did it stick? | **`attempts_on(path)`** in the MCP server, `flask sessions`, or the Python client |
| Who read what through the API? | The **audit log**, one row per API call and per admin action |

**The benefits:**

- **Accountability without overhead.** The hook script is fire-and-forget (2-second timeout, always exits 0), so the agent never waits for Flightlog and never fails because of it.
- **The outcome, not just the activity.** Edits and test runs are easy to count. What matters is whether the PR survived, and Flightlog derives "reverted" from GitHub's own revert PRs.
- **A better next session.** A new agent session can ask what earlier sessions tried on the same file, and get structured facts back instead of raw transcripts.
- **Safe to share.** Reports and agent-facing answers carry counts, relative paths and outcomes, never commands, prompts or file contents.
- **Correct under real-world delivery.** Webhooks arrive twice, late and out of order; Flightlog stores each delivery exactly once and gets the result right anyway.

## The best features

- **Signed, exactly-once ingest.**
  - HMAC-SHA256 is verified over the raw body, compared in constant time.
  - A unique constraint on `(source, delivery_id)` makes duplicates harmless.
  - The response is `202` right after storing; nothing is processed in the request ([ADR-0003](docs/adr/0003-store-then-acknowledge.md), [ADR-0004](docs/adr/0004-idempotency-and-ordering.md)).
- **Order-independent sessions.** A `SessionEnd` that arrives before the session's earlier events still yields a stopped session that starts at its first event. A late event re-computes the summary.
- **A job queue in PostgreSQL.**
  - The worker claims jobs with `FOR UPDATE SKIP LOCKED`, so two workers never take the same job.
  - A failed job is retried with exponential backoff (10 s, 20 s, 40 s, …) and marked failed after 5 attempts.
  - A failed job can be retried from the admin page.
- **Pull requests linked at read time.** A session is linked to the PRs opened from its branch, and "reverted" is derived from a later merged PR whose body says `Reverts owner/repo#N`. Outcomes are never stale ([ADR-0009](docs/adr/0009-link-sessions-to-pull-requests-at-read-time.md)).
- **A timeline with secrets masked.** `GITHUB_TOKEN=…`, `--password …`, `Authorization: Bearer …`, URLs with credentials, `ghp_…` and `sk-ant-…` tokens, and Flightlog's own keys are masked before display.
- **A weekly PDF report.** A Jinja template is rendered in-process and printed by headless Chromium. It is guaranteed one page per repo, and a test with real Chromium checks the page count.
- **A secure read API.**
  - Each client gets its own key, stored as a SHA-256 hash with a visible prefix.
  - Limits are per connector (Redis-backed in Docker), plus a stricter per-IP limit for unauthenticated calls.
  - Every call is audited.
- **Agent-facing summaries.** A stored digest per finished session: files touched (relative to the repo), edits, test runs and tools. It is an allow-list, so no raw tool input ever gets in ([ADR-0018](docs/adr/0018-stored-session-summaries.md)).
- **Three ways for agents to read history:**
  - `flask sessions`: a screenful in the shell;
  - a read-only MCP server with three tools;
  - a typed, dependency-free Python client for cross-session questions.
- **Production manners.**
  - An admin login with scrypt and CSRF tokens.
  - ProxyFix only when you say there is a proxy.
  - A warning at startup for every missing secret.
  - Docker Compose for the whole stack, and a CI job that smoke-tests the containers.

## A tour of the UI

The dashboard is server-rendered HTML with no JavaScript. Every state is a URL you can bookmark, and it follows your system's light or dark mode.

### Login

One admin account, configured as a scrypt password hash. Session cookies are `HttpOnly`, `SameSite=Lax` and `Secure`, and last 12 hours. Login attempts are rate-limited per IP.

<img src="docs/images/login.png" alt="The login page" width="640">

### Sessions

Every agent session, newest first, filtered by repo and status and paged with a keyset cursor. A session whose events are still in the queue says so instead of showing half a timeline.

<img src="docs/images/sessions-dark.png" alt="The session list in dark mode">

### Session timeline

Everything one session did, in the order the agent did it:
- the status and duration;
- the linked pull request and its outcome;
- the files touched;
- each event classified as an edit, a test run, a tool call, or a session start or end.

Note the masked token in the `gh pr create` command.

![A session timeline with its merged pull request, files touched and masked command](docs/images/timeline.png)

### Weekly report

`flask --app flightlog report --week 2026-W47` writes an A4 PDF with one page per repo:
- the sessions;
- time spent;
- test runs;
- pull requests by outcome;
- the most-edited files;
- a table of sessions, capped so the page never overflows.

It contains counts and paths only, never commands. The dashboard shows the same page at `/reports/<week>`.

<img src="docs/images/weekly-report.png" alt="The first page of the weekly report: the flightlog repo's summary, top files and sessions" width="640">

### Failed jobs

When the worker gives up on a delivery after five attempts, it shows up here with its last error. **Retry** queues it again with a fresh set of attempts. The retry is a POST with a CSRF token, and a double click is harmless.

![The failed jobs page with one job and its error](docs/images/failed-jobs.png)

### Connectors

The clients of the read API, each with its own key. Only the prefix is stored in a readable form, so a key can be recognised but not recovered. Revoking takes effect on the next request, and is audited.

![The connectors page: two active keys and a revoked one](docs/images/connectors.png)

### Audit log

Every read API call and every admin action:
- **who:** a connector, the admin, or anonymous, plus the IP address;
- **what:** the method, path and route;
- **which object** it was about;
- **the outcome.**

Refused calls are recorded too: here a revoked key was denied with a 401.

![The audit log with API calls, a denied revoked key and an admin login](docs/images/audit-log.png)

## Keeping the agent in the loop

A new agent session usually starts from scratch. Flightlog lets it start with a short, structured history instead, and stays careful about what it hands back. Summaries hold ids, times, counts, relative paths and outcomes. They never hold raw transcript, command or tool text, because old sessions contain text from web pages and files, and feeding it back would bring injected instructions back with it.

### In the shell: `flask sessions`

Any agent can run this, with no extra server. It defaults to the current folder's repo and prints at most a screenful: two lines per session, at most 120 characters each.

```
$ flask --app flightlog sessions --last 4
Last 4 agent sessions in flightlog, newest first:
2026-11-20 11:00 UTC · running · feat/mcp-server · no PR
  goal: mcp server · running now
2026-11-18 11:00 UTC · 52 min · feat/weekly-report · PR #19 reverted
  goal: Weekly PDF report, one page per repo · 3 files (…ates/report/weekly.html +2) · 1 test run
2026-11-17 11:30 UTC · 1 h 14 min · feat/audit-log · PR #18 merged
  goal: Audit log for API calls and admin actions · 4 files (…79c_create_audit_log.py +3) · 2 test runs
2026-11-16 10:00 UTC · 38 min · feat/rate-limits · PR #17 merged
  goal: Rate limits per connector and on login · 3 files (…tlog/api/rate_limits.py +2) · 2 test runs
```

`--json` gives every field for scripts.

### Inside a session: the MCP server

`flask --app flightlog mcp` serves three read-only tools over stdio, and Claude Code starts it from [`.mcp.json`](.mcp.json):

| Tool | Answers |
| --- | --- |
| `recent_sessions(repo?, last=5)` | The repo's newest sessions: date, goal, files, test runs, outcome |
| `attempts_on(path, repo?, last=10)` | Earlier sessions that edited this file, and what came of them |
| `session_summary(session_id)` | The stored summary of one session |

Asked `attempts_on("src/flightlog/api/rate_limits.py")`, it answers with structured data, trimmed here:

```json
{
  "repo": "flightlog",
  "path": "src/flightlog/api/rate_limits.py",
  "sessions": [
    {
      "id": 1,
      "started_at": "2026-11-16T10:00:00+00:00",
      "branch": "feat/rate-limits",
      "goal": "Rate limits per connector and on login",
      "pull_request": { "number": 17, "title": "Rate limits per connector and on login", "outcome": "merged" },
      "summary_state": "ready",
      "summary": {
        "files_touched": ["src/flightlog/api/rate_limits.py", "src/flightlog/api/read_api.py", "tests/api/test_rate_limits.py"],
        "edits": 4, "test_runs": 2, "tool_calls": 7, "tools": { "Bash": 3, "Edit": 4 },
        "duration_seconds": 2280
      }
    }
  ]
}
```

Flightlog never records calls to its own tools. The hook script skips them, and ingest ignores any that still arrive.

### In a script: the Python client

[`flightlog-client`](client/) is a typed client for the read API. It uses the standard library only, and has no dependency on the app, so it cannot reach the database. An agent imports it in a script, filters and counts there, and only the answer reaches its context:

```python
from collections import Counter
from datetime import date

from flightlog_client import Flightlog, Outcome

reverted = Counter()
for session in Flightlog().summaries("flightlog", since=date(2026, 11, 1)):  # every page
    pr = session.pull_request
    if pr and pr.outcome is Outcome.REVERTED and session.summary:
        reverted.update(session.summary.files_touched)
```

```
$ python client/examples/reverted_files.py --repo flightlog --since 2026-11-01
1 src/flightlog/api/templates/report/weekly.html
1 src/flightlog/application/report.py
1 src/flightlog/infrastructure/pdf.py
```

**When each one pays off** ([ADR-0020](docs/adr/0020-python-client.md)):

| | Use it for | Cost |
| --- | --- | --- |
| `flask sessions` | a glance, no setup | one repo, at most 20 sessions |
| MCP tools | one question inside a session | each answer lands in the agent's context |
| Python client | counting and joining across many sessions | a key and a script; only the printed answer reaches the context |

## How it works

1. **Capture.**
   - Claude Code runs [`scripts/flightlog_hook.py`](scripts/flightlog_hook.py) on `SessionStart`, `PostToolUse`, `Stop` and `SessionEnd`. The script wraps the hook's JSON in an envelope with a delivery id, a timestamp and the current git branch, signs it with HMAC-SHA256, and posts it to `/ingest/claude`.
   - GitHub sends `pull_request` webhooks to `/ingest/github`, signed with the webhook secret.
2. **Store once, acknowledge.** Ingest verifies the signature over the raw bytes, stores the event with a unique `(source, delivery_id)`, enqueues its job **in the same transaction**, and answers `202`. A duplicate also gets `202`, and no second row.
3. **Process.** `flask worker` claims one job at a time with `SELECT … FOR UPDATE SKIP LOCKED`:
   - **`apply_to_session`** creates or updates the session. Its rules are order-independent: the earliest event sets the start, `SessionEnd` sets the end, and the latest event sets the branch.
   - **`apply_pull_request`** keeps the newest snapshot of each PR; a merged PR stays merged.
   - **`summarize_session`** recomputes the session's stored summary on `SessionEnd`, and again for every late event.

   A successful job is deleted in the same transaction as its work. A failed one is retried with backoff.
4. **Read.**
   - The dashboard, report, API, CLI, MCP server and client all read through the same application queries.
   - The PR outcome is always derived when read, so a later revert shows up everywhere at once.

The code is layered, and import-linter enforces the layers in CI ([ADR-0007](docs/adr/0007-layered-architecture.md)):

```
api/             Flask blueprints, CLI commands, MCP server   ── never imports infrastructure
infrastructure/  SQLAlchemy tables, imperative mapping, repositories, Chromium PDF
application/     use cases, behind the Protocols in ports.py
contracts/       commands in, results out (frozen dataclasses)
domain/          AgentSession, PullRequest, Connector: plain dataclasses, no frameworks
```

`create_app` is the composition root: it wires the adapters into `app.extensions`, and the `api` layer takes them from there.

## Security model

| Threat | Defence |
| --- | --- |
| Forged webhooks | HMAC-SHA256 over the raw body, `hmac.compare_digest`; **an empty or missing secret refuses everything** |
| Replayed or duplicated deliveries | Unique `(source, delivery_id)`; a duplicate is acknowledged and ignored |
| Stolen API key | A key per connector, stored as SHA-256 plus a prefix, revocable on its own; one identical 401 for missing, wrong and revoked keys |
| Key guessing, API abuse | Flask-Limiter per connector, a stricter per-IP limit without a valid key, `Retry-After` on 429 |
| Password guessing | scrypt hashes; `POST /login` limited to 5 a minute and 20 an hour per IP |
| CSRF on the dashboard | Synchroniser tokens on every POST; `SameSite=Lax` cookies; logout is a POST too |
| Session fixation, open redirects | The session is cleared at login; `next=` is followed only for local paths |
| Spoofed client IPs | `X-Forwarded-For` is trusted only when `FLASK_PROXY_COUNT` says a proxy is in front |
| Secrets in commands | Masked on the timeline; never stored in summaries, reports or agent answers |
| Prompt injection via history | Agent-facing data is an allow-list of structured fields; PR titles are cleaned to one line and labelled as data |
| Unnoticed access | An audit row for every API call and admin action, refusals included; fail-open with a logged error |

## Getting started

### With Docker (the whole stack)

```bash
cp .env.example .env    # fill in the secrets; single-quote the password hash
docker compose up -d --build --wait
```

This starts PostgreSQL, Redis, a one-off `migrate` service, the app on gunicorn at **http://localhost:8000**, and the worker. The weekly report runs in its own image with Chromium:

```bash
docker compose run --rm report --week 2026-W47      # writes ./reports/flightlog-2026-W47.pdf
```

### For development

```bash
docker compose up -d db                              # PostgreSQL on localhost:5433
python -m venv .venv && source .venv/Scripts/activate    # bin/ on Linux and macOS
pip install -e ".[dev]" -e client && playwright install chromium
cp .env.example .env
alembic upgrade head
flask --app flightlog hash-password                  # paste the hash into .env, in single quotes
flask --app flightlog run --debug                    # http://localhost:5000
flask --app flightlog worker                         # in a second terminal
```

### Connecting Claude Code

The hooks are already wired in [`.claude/settings.json`](.claude/settings.json). Give the hook script its endpoint and secret in `.claude/settings.local.json`, which isn't committed:

```json
{ "env": { "FLIGHTLOG_URL": "http://localhost:5000", "CLAUDE_HOOK_SECRET": "<same as FLASK_CLAUDE_HOOK_SECRET>" } }
```

For the MCP tools, start `claude` in this repo with the virtualenv active and approve the `flightlog` server once.

### Connecting GitHub

In the repository's settings, add a webhook:
- **Payload URL:** `https://<your host>/ingest/github`
- **Content type:** `application/json`
- **Secret:** the value of `FLASK_GITHUB_WEBHOOK_SECRET`
- **Events:** "Pull requests"

## Configuration

Flask reads every `FLASK_*` environment variable (or `.env`), and parses values as JSON where possible.

| Variable | Default | What it does |
| --- | --- | --- |
| `FLASK_DATABASE_URL` | (required) | PostgreSQL URL, e.g. `postgresql+psycopg://flightlog:flightlog@localhost:5433/flightlog` |
| `FLASK_GITHUB_WEBHOOK_SECRET` | none: deliveries refused | HMAC secret shared with the GitHub webhook |
| `FLASK_CLAUDE_HOOK_SECRET` | none: events refused | HMAC secret shared with the hook script |
| `FLASK_SECRET_KEY` | none: no login | Signs the admin session cookie; changing it logs everyone out |
| `FLASK_ADMIN_PASSWORD_HASH` | none: no login | From `flask hash-password`; single-quote it in `.env` |
| `FLASK_SESSION_COOKIE_SECURE` | `true` outside debug | Set `false` only for plain http on localhost |
| `FLASK_PROXY_COUNT` | `0` | Number of trusted proxies in front; turns on ProxyFix |
| `FLASK_RATELIMIT_STORAGE_URI` | `memory://` | `redis://redis:6379/0` in Docker, shared by every gunicorn worker |
| `FLASK_RATELIMIT_API` | `120 per minute` | Per connector, for every `/api/v1` route together |
| `FLASK_RATELIMIT_API_ANONYMOUS` | `20 per minute` | Per IP, for requests without a valid key |
| `FLASK_RATELIMIT_LOGIN` | `5 per minute; 20 per hour` | Per IP, `POST /login` only |
| `FLASK_DASHBOARD_PAGE_SIZE` | `25` | Sessions per dashboard page |
| `FLASK_AUDIT_PAGE_SIZE` | `100` | Rows per audit page |
| `FLASK_DB_CONNECT_TIMEOUT` | `5` | Seconds before a database connection attempt gives up |

The hook script and the client read their own variables: `FLIGHTLOG_URL` and `CLAUDE_HOOK_SECRET` for the hook script, and `FLIGHTLOG_URL` and `FLIGHTLOG_API_KEY` for the client. In Docker, `FLIGHTLOG_APP_PORT` and `FLIGHTLOG_DB_PORT` move the host ports.

## Command reference

| Command | What it does |
| --- | --- |
| `flask --app flightlog run` | The development server (gunicorn in Docker) |
| `flask --app flightlog worker [--once]` | Process queued jobs; Ctrl+C or SIGTERM stops between jobs |
| `flask --app flightlog report [--week 2026-W47] [--out PATH]` | The weekly PDF, one page per repo; default: last full week |
| `flask --app flightlog sessions [--repo] [--last 1..20] [--json]` | Recent sessions for an agent's shell |
| `flask --app flightlog mcp` | The read-only MCP server over stdio |
| `flask --app flightlog connector create\|list\|revoke NAME` | API keys; the key is printed once |
| `flask --app flightlog summaries rebuild` | Queue summaries for stopped sessions without a current one |
| `flask --app flightlog hash-password` | Make `FLASK_ADMIN_PASSWORD_HASH` |

**Read API** (Bearer key; JSON errors; rate-limited; audited):

| Endpoint | Returns |
| --- | --- |
| `GET /api/v1/sessions?repo=&status=&after=&limit=` | Sessions as the dashboard lists them, keyset-paged |
| `GET /api/v1/sessions/<id>` | One session's timeline, commands masked |
| `GET /api/v1/summaries?repo=&path=&since=&after=&limit=` | Stored summaries with PR outcome and goal, keyset-paged |
| `GET /api/v1/sessions/<id>/summary` | One session's stored summary |

## Project layout and engineering

```
src/flightlog/      the app, in the layers above
client/             flightlog-client, the typed read API client (its own package)
scripts/            the Claude Code hook script (standard library only)
migrations/         Alembic migrations, each one reviewed by hand
tests/              domain · application · infrastructure · api · client · e2e · compose
docs/adr/           20 architecture decision records
docs/guide/         a Flask guide for Django developers, and a log per task
```

- **Python 3.13, Flask 3.1, SQLAlchemy 2.1** (imperative mapping, `select()` only), **Alembic**, **PostgreSQL 17**, **Flask-Limiter 4**, **Playwright 1.65**, **mcp 2.3**, **gunicorn**, **Redis**.
- **About 550 tests:**
  - domain and use cases on in-memory fakes;
  - repositories and routes against a real PostgreSQL, each test in a rolled-back transaction;
  - Playwright browser tests against a live server on its own database;
  - full-stack tests with every part as a separate process (`flask run`, the hook script, the worker, `flask mcp` over stdio);
  - a smoke test against `docker compose up`.
- **CI** runs ruff, ruff format, import-linter (three contracts, including "the MCP server never touches infrastructure"), the migrations, the whole suite with Chromium, and a second job that builds both images and smoke-tests the composed stack.

The screenshots in this README are made by [`tests/e2e/screenshots.py`](tests/e2e/screenshots.py). It seeds a throwaway database through the front door (signed hook events, GitHub deliveries, the worker), serves the app and captures each page with Playwright. Run it again after a UI change:

```bash
python -m tests.e2e.screenshots
```

## Further reading

- [The plan](docs/plan.md): milestones M1 to M5 and their acceptance criteria.
- [Architecture decision records](docs/adr/): from [store-then-acknowledge](docs/adr/0003-store-then-acknowledge.md) and [idempotency and ordering](docs/adr/0004-idempotency-and-ordering.md) to [rate limits](docs/adr/0014-rate-limits-per-connector.md), [the audit log](docs/adr/0015-audit-log.md), [containers](docs/adr/0017-containers.md), [stored summaries](docs/adr/0018-stored-session-summaries.md), [the MCP server](docs/adr/0019-read-only-mcp-server.md) and [the client](docs/adr/0020-python-client.md).
- [Flask for Django developers](docs/guide/flask-for-django-devs.md): every Flask choice mapped to Django and Spring, with the gotchas found along the way.
- [The build log](docs/guide/log/): what was built in each task, what was learned, and what is still open.

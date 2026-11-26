# 0010 · Dashboard read models and the session timeline

- Status: Accepted
- Date: 2026-11-18

## Context
M3 task 2 adds a dashboard: a session list, filterable by repo and status, and a timeline per session with tool calls, files touched, test runs, the linked PR and its outcome. The M4 read API and the M5 summaries and MCP server will ask the same questions, so the read side should not be shaped around one consumer.

The facts are already stored: raw hook events in `event_logs.payload` (JSONB), sessions in `agent_sessions`, PRs in `pull_requests`, pending work in `event_jobs`. What the dashboard needs is a reading of those facts: which tool call is a file edit, which Bash command is a test run. Events arrive out of order (ADR-0004), and sessions keep arriving while someone pages through the list.

Hook payloads are untrusted text: commands and paths can contain content copied from web pages and files, and secrets typed on a command line.

## Decision
- **One read port per concept.** `AgentSessionQueries` (application/ports.py) gets `list_sessions(filter)`, `repos()`, `session_summary(session_id)` and `session_events(session_id)`, next to `linked_pull_requests` (ADR-0009). They return frozen read models from `contracts/sessions.py`: `SessionFilter`, `SessionCursor`, `SessionSummary`, `SessionPage`, `SessionEvent`, `TimelineEntryKind`, `TimelineEntry`, `SessionTimeline`. No `DashboardQueries` port: the API and MCP server reuse the same methods.
- **Filtering in SQL, keyset paging.** The API parses `request.args` into a `SessionFilter` (unknown status or cursor → 400). Sessions are ordered by `(started_at DESC, id DESC)` and paged with `(started_at, id) < cursor` and an "Older" link. Offset paging would show a row twice whenever a new session arrives between two pages.
- **One ordered event stream, classified in Python.** `session_events` selects the session's events ordered by **`occurred_at, id`**: the sender's clock decides (ADR-0004), `id` only breaks ties. It extracts just `type`, `tool_name`, `tool_input.file_path` and `tool_input.command` from the JSONB, never `tool_response` (large, and raw tool text). In `application/timeline.py`:
  - `classify(event) -> TimelineEntryKind`, a pure function: Edit, Write, MultiEdit and NotebookEdit are file edits (reads are not "touched"); a Bash command starting with a command from a fixed list (`pytest`, `npm test`, …) is a test run; other tools are plain tool calls; SessionStart, Stop and SessionEnd are markers.
  - `mask_secrets(command) -> str`, a pure function next to `classify`: hides likely secrets (`TOKEN=…`, `--password …`, `Authorization: …`, `fl_…` keys) before a command reaches any read model.
  - `session_timeline(session_id, queries) -> SessionTimeline | None`: summary, classified and masked entries, distinct sorted `files_touched`, the test-run count and `linked_pull_requests`. The PR is an outcome panel, not part of the stream: a link has no event time of its own.
- **Pending events per session.** `SessionSummary.pending_events` counts this session's events that still have a job in `event_jobs` with `failed_at IS NULL` (log 01: `processed_at` is not "pending"). The worker only sets `event_logs.agent_session_id` when it applies an event, so a pending event is matched on `source` and `payload->'hook'->>'session_id' = agent_sessions.external_id`, not on the foreign key. Failed jobs belong to the admin page (task 3).
- **An index for the timeline:** `event_logs (agent_session_id, occurred_at, id)`. PostgreSQL does not index foreign keys by itself.
- **Times are shown in UTC.** The PR outcome appears only on the timeline page, not in the list (no per-row PR lookup, no N+1).
- **Untrusted text is never trusted.** Jinja's autoescaping stays on and payload data never goes through `|safe`. Masking and escaping solve different problems (leaking a secret vs. running a script) and neither replaces the other.

Alternatives considered: one query per section (tool calls, files, tests), which spreads the classification rule over SQL `CASE`s; and a projection table filled by the worker (a proper CQRS projection, but a migration, a backfill and idempotent projection logic before there is a need; M5's stored summaries are the moment for that).

## Consequences
- The rules that interpret Claude Code's payload (`classify`, `mask_secrets`) are tested without Flask or a database, like `repo_name` in `apply_to_session`.
- The timeline lags the queue: an event only joins it once the worker has applied it. The pending count makes that lag visible instead of hiding it.
- The pending count matches on a JSONB expression without an index. Fine for one developer's data; an expression index on `(source, (payload->'hook'->>'session_id'))` fixes it if it gets slow.
- Test runs are recognised, but not judged: whether a `PostToolUse` Bash payload carries an exit code depends on the Claude Code version (to check in its hook docs), and parsing stdout is out (M5 rule: no raw tool text). Pass/fail stays open.
- Test-run detection by a fixed command list misses wrappers (`make test`, `uv run pytest`) until they are added to the list.
- Masking is best-effort: a secret in an unusual shape still shows. The page is local (ADR-0011), which limits who sees it.
- One extra migration (the index).

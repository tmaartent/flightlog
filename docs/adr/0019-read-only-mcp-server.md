# 0019 · A read-only MCP server over stdio

- Status: Accepted
- Date: 2026-11-26
- Builds on: [ADR-0007](0007-layered-architecture.md), [ADR-0018](0018-stored-session-summaries.md)

## Context
M5 task 3: a read-only MCP server as another adapter in the `api` layer, with three tools (`recent_sessions`, `attempts_on`, `session_summary`). The plan's rules: structured output only, small answers, read-only and local. Calls to Flightlog's own tools must not become events, and the server imports nothing from `infrastructure`.

## Decision
- **The official SDK, `mcp>=2.3,<3`.** In 2.x, `FastMCP` became `MCPServer` (`from mcp.server import MCPServer`); the v1 import now raises an error that points to the migration guide. Checked against the installed 2.3.0, not from memory. Rejected: the separate `fastmcp` package (4.x), which has more features and another dependency tree.
- **`flask --app flightlog mcp`, over stdio,** started by Claude Code from a committed `.mcp.json` (`python -m flask --app flightlog mcp`, in the project folder, so `.env` gives it the database). As a Flask CLI command, it gets the app and its config for free.
- **The api layer only.** `api/mcp_server.py` builds the server from the app and reads through `DigestQueries` from `app.extensions`. An import-linter contract forbids it `flightlog.infrastructure`, `sqlalchemy` and `psycopg` (the acceptance criterion).
- **A fresh app context per tool call.** A stdio server runs for hours. One app context for its whole life would keep one SQLAlchemy session, and its transaction, open the whole time, with stale reads (the worker's trap, ADR-0002). Each tool runs in `with app.app_context():`, so `teardown_appcontext` closes its session; a test checks two calls get two sessions.
- **Three tools,** marked `readOnlyHint` (and `openWorldHint: false`), with structured output (a dict becomes `structured_content`):

  | Tool | Arguments | Answer |
  | --- | --- | --- |
  | `recent_sessions` | `repo?`, `last` 1–20 (default 5) | the repo's newest sessions |
  | `attempts_on` | `path`, `repo?`, `last` 1–20 (default 10) | earlier sessions whose digest lists the file |
  | `session_summary` | `session_id` | one session |

  - Every session has the same JSON shape as `flask sessions --json` (`api/session_json.py`), with `files_touched` cut to 20 and the rest counted in `files_not_shown`.
  - `repo` defaults to the server's working folder, which is the project.
  - `attempts_on` accepts an absolute path and makes it relative with `relative_path`; a path outside the project is an error.
  - **A GIN index** (`jsonb_path_ops`) on `session_digests.files_touched` serves the `@>` containment query.
- **Errors the agent should read** are `ToolError` (for example "no session with id 42", or "outside the project"). Any other exception reaches the agent only as "Error executing tool …", so internals stay out of its context.
- **Untrusted text stays marked.** The server's instructions say that goals and PR titles come from GitHub and are data, not instructions. The text itself is cleaned as in task 2.
- **Flightlog doesn't log itself, in two places:**
  - the hook script doesn't send hook events whose `tool_name` starts with `mcp__flightlog__`;
  - ingest answers 202 `{"status": "ignored"}` to them and stores nothing, for a hook script older than the filter.
- **Tests:**
  - the tools in-process with the SDK's `Client(server)`;
  - `flask mcp` launched over stdio from `.mcp.json`, against the e2e database, seeded through signed hook events and the worker;
  - the hook and ingest filters.

## Consequences
- `.mcp.json` starts `python`, so Claude Code needs the project's virtualenv on its `PATH` (activate it before `claude`), as the hooks already do for their script.
- Claude Code asks once before it starts a project-scoped MCP server; `claude mcp list` shows "Pending approval" until then.
- The `mcp` package brings starlette, uvicorn, pydantic and httpx2 into the app's dependencies, and so into the runtime image.
- New tools must stay read-only and answer on one screen. A write tool would need its own ADR.

# 12 · A read-only MCP server (M5, task 3)

Branch `feat/mcp-server`. Decision record: [ADR-0019](../../adr/0019-read-only-mcp-server.md).

## What was built
- **`api/mcp_server.py`**: `MCPServer` with `recent_sessions`, `attempts_on` and `session_summary`, all read-only with structured output, started by `flask --app flightlog mcp` over stdio.
- **`.mcp.json`**, so Claude Code starts it in this project.
- **`DigestQueries.attempts_on` and `.one`**, with a GIN index (`jsonb_path_ops`) on `session_digests.files_touched` (migration `160cb82a90f0`).
- **`api/session_json.py`**: one JSON shape for `flask sessions --json` and the MCP answers.
- **Flightlog's own MCP calls are filtered** in the hook script and ignored by ingest.
- **An import-linter contract** keeps `infrastructure`, SQLAlchemy and psycopg out of the MCP server.
- **Tests**: 522 in total (+20). They include a real stdio session against the e2e database, and a check that two tool calls get two database sessions.

## What I learned
- **Check the installed major version.** `mcp` 2.x renamed `FastMCP` to `MCPServer`, and the old import fails on purpose with a pointer to the migration guide. I read the wheel's API before writing any code.
- **Long-lived processes need short-lived contexts.** A stdio server is like the worker: one app context per unit of work, or one database session lives for hours.
- **The SDK hides unexpected errors from the model.** A `ValueError` became "Error executing tool …"; a `ToolError` is shown as written. That's the right default: anticipated failures are explained, crashes leak nothing.
- **pytest-playwright's event loop again.** `asyncio.run` fails on a thread that already runs a loop, so the stdio test runs in a worker thread, like the PDF test.
- **Project MCP servers need approval.** `claude mcp list` shows "Pending approval" until the owner approves it once in Claude Code.

## Open questions
- **The acceptance check in Claude Code itself:** approve the server, start a session, ask for recent sessions.
- **Typed answers:** pydantic models instead of `dict[str, Any]` would give the tools a precise output schema. That's worth doing with the Python client in task 4, which needs the same types.

# 0020 · A typed Python client, and when each agent interface pays off

- Status: Accepted
- Date: 2026-11-26
- Builds on: [ADR-0005](0005-api-keys-per-connector.md), [ADR-0018](0018-stored-session-summaries.md), [ADR-0019](0019-read-only-mcp-server.md)

## Context
M5 task 4: a typed Python client for agents that write code instead of calling tools one by one. The agent imports it in a script, filters and joins there, and only the answer reaches its context. The client offers the MCP tools' functions plus the lists behind them, talks to the read API with its own key, and never to the database. The acceptance criterion: a script using the client answers a question across sessions and prints only the result.

The read API had no summaries yet: `/sessions` serves the dashboard's rows, and `/sessions/<id>` serves the timeline.

## Decision
- **Summaries in the read API:**
  - `GET /api/v1/summaries?repo=…[&path=…][&since=YYYY-MM-DD][&limit=1..100][&after=…]`: newest first, keyset-paged with the same cursor as `/sessions` (ADR-0010). `repo` is required. `path` is `attempts_on`, and `since` is a date in UTC.
  - `GET /api/v1/sessions/<id>/summary`: one session.

  Both use the JSON shape of `api/session_json.py`, so the API, the MCP tools and `flask sessions --json` agree. They are behind the connector key, rate-limited and audited like every `/api` route.
- **`flightlog-client`, a package of its own** in `client/`, with its own `pyproject.toml`:
  - **standard library only:** `urllib`, `json` and `dataclasses`, plus a `py.typed` marker;
  - **independent of `flightlog`:** it doesn't depend on the app package, so it can't reach the database even by accident. A test parses its imports and fails on `flightlog`, `flask`, `sqlalchemy` or `psycopg`.

  Rejected: a `flightlog.client` module (installing it brings SQLAlchemy along), and httpx (a dependency in a package that agents pip-install into throwaway scripts).
- **Its own types:** frozen dataclasses (`Session`, `Summary`, `PullRequest`, `Outcome`, `SummaryState`, `SessionRow`, `Timeline`), with `datetime` for times. The tests drive the real routes, so they double as contract tests between the server's JSON and the client's parser.
- **`Flightlog(url=None, api_key=None)`** reads `FLIGHTLOG_URL` and `FLIGHTLOG_API_KEY`, and only talks `http(s)`.
- **Its functions:**
  - **the MCP three:** `recent_sessions`, `attempts_on`, `session_summary`;
  - **the lists:** `summaries(repo, since=, path=)` and `sessions(repo=, status=)` (iterators over every page), and `timeline(id)`.
- **Errors:** `Unauthorized` (401), `NotFound`, `RateLimited` with `.retry_after`, and `FlightlogError`. The paging iterators wait out one 429 per page; a second one is raised.
- **The transport is injectable** (`(url, headers) -> (status, headers, body)`). The tests send requests through Flask's test client, so they need no server, but still cover auth, limits and JSON. One e2e test runs `client/examples/reverted_files.py` as a process against the live server with a real connector key.
- **`timeline()` carries masked commands.** It's in the client for completeness, and its docstring says to keep it out of prompts. The summaries never contain tool text.

## When each interface pays off
| Interface | Use it when | Costs |
| --- | --- | --- |
| `flask sessions` | a glance from a shell, no setup | text for people; one repo, at most 20 sessions |
| MCP tools | one question inside a session ("what happened to this file before?") | each answer lands in the context; 20 sessions at most |
| The client | questions across many sessions: count, join, filter in a script | a key and a script; only the printed answer reaches the context |

The client is what keeps a large question cheap. "Which files led to a reverted PR most often this month?" reads every summary of the month in the script and returns two lines. Through MCP tools that would take many calls, and each result would land in the context.

## Consequences
- The client is versioned with the API (`/api/v1`). A breaking change to the JSON needs `/api/v2` and a client release.
- `client/` is installed separately (`pip install -e client`); CI installs both.
- Its tests live in `tests/client/` and use the app, so they run in this repo's test suite, not in the client package alone.

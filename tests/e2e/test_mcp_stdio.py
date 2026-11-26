"""`flask mcp` as Claude Code starts it: a process, spoken to over stdio (M5, ADR-0019).

The acceptance test short of Claude Code itself: a client launches the server the way
.mcp.json does, calls recent_sessions and gets structured data back. Seeded through the front
door: hook events signed like the hook script signs them, then the worker.
"""

import asyncio
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from mcp import Client, StdioServerParameters

from tests.e2e.flows import AgentSessionScript, run_worker
from tests.harness import E2E_DATABASE_URL, REPO_ROOT

MCP_JSON = REPO_ROOT / ".mcp.json"


def server_parameters(cwd: Path) -> StdioServerParameters:
    """What .mcp.json says, pointed at the e2e database instead of the developer's."""
    config = json.loads(MCP_JSON.read_text(encoding="utf-8"))["mcpServers"]["flightlog"]
    command = sys.executable if config["command"] == "python" else config["command"]
    return StdioServerParameters(
        command=command,
        args=config["args"],
        env={**os.environ, "FLASK_SKIP_DOTENV": "1", "FLASK_DATABASE_URL": E2E_DATABASE_URL},
        cwd=cwd,
    )


async def ask(parameters: StdioServerParameters, tool: str, **arguments):
    async with Client(parameters, read_timeout_seconds=30) as client:
        names = [t.name for t in (await client.list_tools()).tools]
        return names, await client.call_tool(tool, arguments)


def test_a_new_session_can_call_recent_sessions_over_stdio(e2e_app, tmp_path):
    (
        AgentSessionScript(e2e_app, "5e5510n-mcp", repo="flightlog", branch="feat/mcp")
        .start(0)
        .edit(1, "/work/flightlog/src/flightlog/api/mcp_server.py")
        .bash(2, "pytest -q")
        .end(9)
    )
    run_worker(e2e_app)  # applies the events, then computes the digest
    project = tmp_path / "flightlog"  # Claude Code starts the server in the project folder
    project.mkdir()

    # pytest-playwright keeps an event loop running on this thread: asyncio.run needs another.
    with ThreadPoolExecutor(max_workers=1) as pool:
        names, result = pool.submit(
            asyncio.run, ask(server_parameters(project), "recent_sessions")
        ).result()

    assert sorted(names) == ["attempts_on", "recent_sessions", "session_summary"]
    assert not result.is_error, result.content
    (session,) = result.structured_content["sessions"]
    assert result.structured_content["repo"] == "flightlog"
    assert session["goal"] == "mcp"
    assert session["summary"]["files_touched"] == ["src/flightlog/api/mcp_server.py"]
    assert session["summary"]["test_runs"] == 1
    assert "pytest" not in json.dumps(result.structured_content)  # no command, ever


@pytest.mark.parametrize("key", ["command", "args"])
def test_mcp_json_starts_flask_mcp(key):
    config = json.loads(MCP_JSON.read_text(encoding="utf-8"))["mcpServers"]["flightlog"]

    assert config[key]
    assert config["args"][-1] == "mcp"

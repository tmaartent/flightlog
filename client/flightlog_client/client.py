"""The Flightlog read API client (ADR-0020). Standard library only."""

import datetime
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterator
from typing import Any

from flightlog_client.models import (
    Session,
    SessionRow,
    Timeline,
    parse_session,
    parse_session_row,
    parse_timeline,
)

# GET url with headers -> (status, headers, body). Injectable, so tests need no server.
Transport = Callable[[str, dict[str, str]], tuple[int, dict[str, str], bytes]]


class FlightlogError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(f"{status}: {message}")
        self.status = status
        self.message = message


class Unauthorized(FlightlogError):
    """401: no key, a wrong key or a revoked one. The server doesn't say which."""


class NotFound(FlightlogError):
    pass


class RateLimited(FlightlogError):
    def __init__(self, status: int, message: str, retry_after: int) -> None:
        super().__init__(status, message)
        self.retry_after = retry_after  # seconds, from the Retry-After header


def urllib_transport(timeout: float) -> Transport:
    def send(url: str, headers: dict[str, str]) -> tuple[int, dict[str, str], bytes]:
        if not url.startswith(("http://", "https://")):
            raise ValueError(f"not an http(s) URL: {url}")  # urlopen also opens file: URLs
        request = urllib.request.Request(url, headers=headers)  # noqa: S310
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
                return response.status, dict(response.headers), response.read()
        except urllib.error.HTTPError as error:
            return error.code, dict(error.headers), error.read()

    return send


class Flightlog:
    """Past agent sessions, from Flightlog's read API, with a connector's own key.

    >>> fl = Flightlog()  # FLIGHTLOG_URL and FLIGHTLOG_API_KEY from the environment
    >>> for s in fl.summaries("shop", since=datetime.date(2026, 11, 1)): ...
    """

    def __init__(
        self,
        url: str | None = None,
        api_key: str | None = None,
        *,
        transport: Transport | None = None,
        timeout: float = 10,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        url = url or os.environ.get("FLIGHTLOG_URL")
        api_key = api_key or os.environ.get("FLIGHTLOG_API_KEY")
        if not url or not api_key:
            raise ValueError("pass url and api_key, or set FLIGHTLOG_URL and FLIGHTLOG_API_KEY")
        self._base = url.rstrip("/") + "/api/v1"
        self._headers = {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}
        self._send = transport or urllib_transport(timeout)
        self._sleep = sleep

    # --- the MCP tools' three questions -------------------------------------------------

    def recent_sessions(self, repo: str, last: int = 5) -> list[Session]:
        """The repo's newest sessions with their summaries."""
        body = self._get("/summaries", {"repo": repo, "limit": last})
        return [parse_session(s) for s in body["summaries"]]

    def attempts_on(self, path: str, repo: str, last: int = 10) -> list[Session]:
        """Earlier sessions in the repo that edited this file (relative to the repo)."""
        body = self._get("/summaries", {"repo": repo, "path": path, "limit": last})
        return [parse_session(s) for s in body["summaries"]]

    def session_summary(self, session_id: int) -> Session:
        return parse_session(self._get(f"/sessions/{session_id}/summary")["session"])

    # --- the lists behind them ----------------------------------------------------------

    def summaries(
        self,
        repo: str,
        *,
        since: datetime.date | None = None,
        path: str | None = None,
        page_size: int = 100,
    ) -> Iterator[Session]:
        """Every summary in the repo, newest first, page by page. Waits out one 429."""
        params = {"repo": repo, "path": path, "limit": page_size}
        if since is not None:
            params["since"] = since.isoformat()
        for item in self._pages("/summaries", "summaries", params):
            yield parse_session(item)

    def sessions(self, repo: str | None = None, status: str | None = None) -> Iterator[SessionRow]:
        """Every session as the dashboard lists it (no summary), newest first."""
        params = {"repo": repo, "status": status, "limit": 100}
        for item in self._pages("/sessions", "sessions", params):
            yield parse_session_row(item)

    def timeline(self, session_id: int) -> Timeline:
        """A session's events. Its commands are masked, but still tool text: not for prompts."""
        return parse_timeline(self._get(f"/sessions/{session_id}"))

    # --- HTTP -----------------------------------------------------------------------------

    def _pages(self, endpoint: str, key: str, params: dict[str, Any]) -> Iterator[dict[str, Any]]:
        after = None
        while True:
            try:
                body = self._get(endpoint, {**params, "after": after})
            except RateLimited as limited:
                self._sleep(limited.retry_after)  # once per page; a second 429 is raised
                body = self._get(endpoint, {**params, "after": after})
            yield from body[key]
            after = body["next"]
            if after is None:
                return

    def _get(self, endpoint: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        # A dict, not **kwargs: the API has a query parameter called `path`.
        query = urllib.parse.urlencode({k: v for k, v in (params or {}).items() if v is not None})
        url = f"{self._base}{endpoint}" + (f"?{query}" if query else "")
        status, headers, body = self._send(url, self._headers)
        data = json.loads(body) if body else {}
        if status == 200:
            return data
        message = data.get("error", "") if isinstance(data, dict) else ""
        if status == 401:
            raise Unauthorized(status, message)
        if status == 404:
            raise NotFound(status, message)
        if status == 429:
            retry_after = {k.lower(): v for k, v in headers.items()}.get("retry-after", "60")
            raise RateLimited(status, message, int(retry_after))
        raise FlightlogError(status, message)

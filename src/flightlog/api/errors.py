"""HTTP errors as JSON for the machine-facing URLs, Flask's HTML page for the rest.

Registered on the app, not on a blueprint: when no route matches (`/api/v1/nope`), Flask
doesn't know which blueprint the URL was meant for, so only an app-level handler sees it.
"""

from flask import request
from flask.typing import ResponseReturnValue
from werkzeug.exceptions import HTTPException

JSON_PREFIXES = ("/api/", "/ingest/")


def handle_http_error(error: HTTPException) -> ResponseReturnValue:
    if not request.path.startswith(JSON_PREFIXES):
        return error  # an HTTPException is itself a response: Flask's HTML error page
    # Keep headers such as Allow (405) and Retry-After (429); the body becomes JSON.
    headers = [(k, v) for k, v in error.get_headers() if k.lower() != "content-type"]
    return {"error": error.description}, error.code or 500, headers

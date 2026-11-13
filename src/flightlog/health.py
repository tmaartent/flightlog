from flask import Blueprint
from flask.typing import ResponseReturnValue
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from .db import get_session

bp = Blueprint("health", __name__, url_prefix="/health")


@bp.route("")
def health() -> ResponseReturnValue:
    try:
        get_session().execute(text("SELECT 1"))
    except OperationalError:
        return {"status": "degraded", "db": "down"}, 503

    return {"status": "ok", "db": "ok"}, 200

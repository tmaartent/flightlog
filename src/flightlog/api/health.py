from flask import Blueprint, current_app
from flask.typing import ResponseReturnValue

from flightlog.application.ports import DatabaseProbe

bp = Blueprint("health", __name__, url_prefix="/health")


@bp.route("")
def health() -> ResponseReturnValue:
    database_is_reachable: DatabaseProbe = current_app.extensions["database_probe"]
    if not database_is_reachable():
        return {"status": "degraded", "db": "down"}, 503

    return {"status": "ok", "db": "ok"}, 200

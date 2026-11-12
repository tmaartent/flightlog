from flask import Blueprint

bp = Blueprint("health", __name__, url_prefix="/health")


@bp.route("")
def health():
    return {"status": "ok"}

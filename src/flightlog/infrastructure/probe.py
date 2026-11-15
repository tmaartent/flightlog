from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from flightlog.infrastructure.db import get_session


def database_is_reachable() -> bool:
    """DatabaseProbe: SELECT 1 on the request's session; False when the database is unreachable."""
    try:
        get_session().execute(text("SELECT 1"))
    except OperationalError:
        return False
    return True

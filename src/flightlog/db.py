from flask import current_app, g
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker


def init_app(app):
    # Without a connect timeout, an unreachable database blocks a request indefinitely.
    engine = create_engine(
        app.config["DATABASE_URL"],
        connect_args={"connect_timeout": app.config.get("DB_CONNECT_TIMEOUT", 5)},
    )
    app.extensions["db"] = engine
    app.extensions["sessionmaker"] = sessionmaker(bind=engine)
    app.teardown_appcontext(close_session)


def get_session() -> Session:
    """The session for the current request: created on first use, reused after that."""
    if "db_session" not in g:
        factory: sessionmaker = current_app.extensions["sessionmaker"]
        g.db_session = factory()

    return g.db_session


def close_session(exc: BaseException | None) -> None:
    """Teardown: return the connection to the pool, also when the request failed."""
    session: Session | None = g.pop("db_session", None)
    if session is not None:
        session.close()

import datetime

from flask import Flask
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix

REQUIRED_SECRETS = {
    "GITHUB_WEBHOOK_SECRET": "every GitHub delivery is refused",
    "CLAUDE_HOOK_SECRET": "every Claude Code hook event is refused",
    "SECRET_KEY": "nobody can log in",
    "ADMIN_PASSWORD_HASH": "nobody can log in",
}


def create_app(test_config=None):
    """The composition root: the one place that knows every layer and wires them together."""
    # Templates and static files are presentation, so they live with the api layer.
    app = Flask(__name__, template_folder="api/templates", static_folder="api/static")
    # The admin session cookie (ADR-0012). Secure needs https, except in local debug mode.
    # Set before reading the environment, so FLASK_SESSION_COOKIE_* can still override it.
    # (Not setdefault: Flask's defaults already hold these keys, so it would change nothing.)
    app.config.update(
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=not app.debug,
        PERMANENT_SESSION_LIFETIME=datetime.timedelta(hours=12),
    )
    app.config.from_prefixed_env()

    if test_config is not None:
        app.config.update(test_config)

    from flightlog.api import (
        admin,
        audit,
        auth,
        connectors,
        dashboard,
        errors,
        health,
        ingest,
        rate_limits,
        read_api,
        report,
        worker,
    )
    from flightlog.infrastructure import db
    from flightlog.infrastructure.agent_session_queries import (
        request_agent_session_queries,
        request_report_queries,
    )
    from flightlog.infrastructure.audit_log import new_audit_log, request_audit_queries
    from flightlog.infrastructure.connector_repository import request_connector_queries
    from flightlog.infrastructure.job_queue import request_job_queries
    from flightlog.infrastructure.mapping import start_mappers
    from flightlog.infrastructure.pdf import ChromiumPdfRenderer
    from flightlog.infrastructure.probe import database_is_reachable
    from flightlog.infrastructure.unit_of_work import new_unit_of_work, request_unit_of_work

    start_mappers()
    db.init_app(app)
    app.extensions["unit_of_work"] = request_unit_of_work
    app.extensions["worker_unit_of_work"] = new_unit_of_work
    app.extensions["agent_session_queries"] = request_agent_session_queries
    app.extensions["job_queries"] = request_job_queries
    app.extensions["report_queries"] = request_report_queries
    app.extensions["pdf_renderer"] = ChromiumPdfRenderer
    app.extensions["connector_queries"] = request_connector_queries
    app.extensions["audit_log"] = new_audit_log
    app.extensions["end_request_session"] = db.end_request_session
    app.extensions["audit_queries"] = request_audit_queries
    app.extensions["database_probe"] = database_is_reachable

    app.register_error_handler(HTTPException, errors.handle_http_error)
    app.register_blueprint(health.bp)
    app.register_blueprint(ingest.bp)
    app.register_blueprint(worker.bp)
    app.register_blueprint(auth.bp)
    app.register_blueprint(dashboard.bp)
    app.register_blueprint(admin.bp)
    app.register_blueprint(read_api.bp)
    app.register_blueprint(connectors.bp)
    app.register_blueprint(report.bp)
    rate_limits.init_app(app)
    audit.init_app(app)

    # Started without a secret, Flightlog still runs, but refuses what that secret protects:
    # deliveries get a 401 and the login page says it isn't configured. Say so at startup.
    for name, refused in REQUIRED_SECRETS.items():
        if not app.config.get(name):
            app.logger.warning("%s is not set: %s", name, refused)

    # Behind N proxies, trust the last N X-Forwarded-For/-Proto values (ADR-0017). Without a
    # proxy they are set by the client, so trusting them would let it pick its own IP.
    proxies = int(app.config.get("PROXY_COUNT", 0))
    if proxies > 0:
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=proxies, x_proto=proxies)

    return app

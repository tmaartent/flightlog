from flask import Flask


def create_app(test_config=None):
    """The composition root: the one place that knows every layer and wires them together."""
    app = Flask(__name__)
    app.config.from_prefixed_env()

    if test_config is not None:
        app.config.update(test_config)

    from flightlog.api import health, ingest, worker
    from flightlog.infrastructure import db
    from flightlog.infrastructure.mapping import start_mappers
    from flightlog.infrastructure.probe import database_is_reachable
    from flightlog.infrastructure.unit_of_work import new_unit_of_work, request_unit_of_work

    start_mappers()
    db.init_app(app)
    app.extensions["unit_of_work"] = request_unit_of_work
    app.extensions["worker_unit_of_work"] = new_unit_of_work
    app.extensions["database_probe"] = database_is_reachable

    app.register_blueprint(health.bp)
    app.register_blueprint(ingest.bp)
    app.register_blueprint(worker.bp)

    return app

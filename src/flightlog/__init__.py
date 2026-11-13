from flask import Flask


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.from_prefixed_env()

    if test_config is not None:
        app.config.update(test_config)

    from . import db, health

    db.init_app(app)
    app.register_blueprint(health.bp)

    return app

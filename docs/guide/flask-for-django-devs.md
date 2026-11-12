# Flask for Django developers

Flask is a small core plus your own choices. Django gives you the house; Flask gives you a good foundation and lets you pick the rooms. This page maps what you know to what Flask does. Add a row whenever something surprises you.

| Django | Flask | Spring equivalent | Note |
| --- | --- | --- | --- |
| `settings.py` | `app.config` (a dict), filled in `create_app` via `from_mapping`, `from_object` or `from_prefixed_env()` | `application.yml` | No settings module: config lives on the app object. |
| Project with `wsgi.py` | **App factory** `create_app(config=None)` | `@SpringBootApplication` | The factory makes testing with a different config trivial and avoids import cycles. |
| App (`catalog/`) | **Blueprint**: routes, templates and error handlers under a URL prefix | `@RestController` + `@RequestMapping("/prefix")` | A blueprint has no models or migrations of its own. |
| `urls.py` + view functions | `@bp.route("/x", methods=["POST"])` or `@bp.post("/x")` | `@PostMapping` | Routing sits on the function itself. |
| `request` passed into the view | Global `request` proxy | `HttpServletRequest`, request-scoped | Thread- or context-local: it only works inside a request context. |
| Middleware | `before_request`, `after_request`, `teardown_request` / `teardown_appcontext` | `HandlerInterceptor`, `Filter` | Per app or per blueprint. |
| `request` attributes for per-request state | `flask.g` | A request-scoped bean | Lives for one app context. Ideal for the DB session (ADR-0002). |
| `django.conf.settings` anywhere | `current_app` | `ApplicationContext` | Also a proxy; needs an app context (outside a request: `with app.app_context():`). |
| ORM + `makemigrations` | SQLAlchemy 2 + Alembic (`alembic revision --autogenerate`) | JPA/Hibernate + Flyway | Autogenerate misses things (renames, server defaults, some type changes): always read the migration. |
| `manage.py <command>` | `flask --app flightlog <command>`, defined with `@app.cli.command()` (click) | `CommandLineRunner` | You'll use it for `worker` and `report`. |
| Templates | Jinja2 | Thymeleaf | Close to Django template syntax, but with real expressions and macros. |
| DRF serializers / `JsonResponse` | Return a `dict` or `list` → JSON automatically; `jsonify` for the rest | `ResponseEntity` | No serializer layer built in. Dataclasses or Pydantic if you need one. |
| `Http404`, exception middleware | `abort(401)`, `@bp.errorhandler(...)`, `@app.errorhandler(HTTPException)` | `@ControllerAdvice` | Return JSON errors for API blueprints, HTML for the dashboard. |
| `django.test.Client` | `app.test_client()`, `app.test_cli_runner()` | `MockMvc` | Make a `client` fixture in `conftest.py` from `create_app(test_config)`. |

## Things that bite

- **Raw body for signatures.** Verify HMAC on `request.get_data()`, the exact bytes received, never on re-serialised JSON. Key order and whitespace would differ.
- **The two contexts.** The *app context* (`current_app`, `g`) and the *request context* (`request`, `session`). A CLI command or the worker has an app context but no request context.
- **`g` is not a cache.** It's gone after the request. Don't store anything there you need next time.
- **`debug=True` is not for production.** Run under gunicorn in Docker (`gunicorn "flightlog:create_app()"`).
- **`flask.session` is a signed cookie,** not server-side storage, and has nothing to do with the SQLAlchemy session. Don't mix them up in an interview answer.

## Interview angles

- "Why an app factory?" Testability (a fresh app per test with its own config), no global state at import time, several configs side by side.
- "How do you manage the DB session in Flask?" One per request on `g`, closed in teardown; commit at the end of the unit of work, roll back on error.
- "Flask or Django?" Django when you want admin, auth and ORM out of the box. Flask when you integrate systems and want a small, explicit service, which is usually the case for middleware.

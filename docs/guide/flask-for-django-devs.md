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
| `handler404` / `handler500` in the root `urls.py` | `app.register_error_handler(HTTPException, handle)` once in `create_app` | `@ControllerAdvice` with `@ExceptionHandler` | One app-level handler sees every HTTP error, also for URLs that match no route. Flightlog picks JSON for `/ingest` and `/api`, HTML otherwise. |
| `TEMPLATES["DIRS"]`, `STATICFILES_DIRS` | `Flask(__name__, template_folder=..., static_folder=...)` | `spring.thymeleaf.prefix`, `/static` on the classpath | Paths are relative to the package. Flightlog keeps both under `api/`, the presentation layer, and lists them as package data so a wheel includes them. |
| `request.GET["status"]` | `request.args.get("status")`, a `MultiDict` | `@RequestParam` | Missing keys give `None`, not an error. Raise `BadRequest` yourself for bad values, as `api/session_filter.py` does. |
| `{% url "name" arg %}` / `reverse()` | `url_for("blueprint.endpoint", **values)` | `MvcUriComponentsBuilder` | Values that aren't route parameters become the query string, and `None` values are left out, which is handy for optional filters. |
| A custom template filter (`@register.filter` + `{% load %}`) | `@bp.app_template_filter("utc")` | A Thymeleaf dialect or utility object | `app_template_filter` registers it app-wide, even though it's declared on a blueprint. No `{% load %}` needed. |
| `LiveServerTestCase` | `werkzeug.serving.make_server(host, 0, app, threaded=True)` in a thread | `@SpringBootTest(webEnvironment = RANDOM_PORT)` | Port 0 picks a free port. The server's threads can't share the test's transaction, so browser tests get their own database (ADR-0013). |
| `django.contrib.auth` + `@login_required` | `bp.before_request(require_admin)`: one function guards every view of a blueprint | A Spring Security filter chain on a path | Flask has no auth built in. One admin with a password hash and a flag in `flask.session` is enough here (ADR-0012). |
| `CsrfViewMiddleware` + `{% csrf_token %}` | Nothing built in; Flightlog's `check_csrf` in `before_request` and a `csrf_token()` template global | Spring Security's `CsrfFilter` | The synchroniser-token pattern, about 20 lines. Flask-WTF's `CSRFProtect` is the library option. |
| `messages.success(request, ...)` | `flash(message, category)` + `get_flashed_messages(with_categories=True)` | `RedirectAttributes.addFlashAttribute` | Stored in the session cookie until the next page reads it, which is what makes Post/Redirect/Get show a message. |
| A template context processor | `@bp.app_context_processor` returning a dict | `@ControllerAdvice` + `@ModelAttribute` | Values or functions every template can use, such as `csrf_token()` and `is_admin`. |
| `make_password` / `check_password` | `werkzeug.security.generate_password_hash` / `check_password_hash` | `PasswordEncoder` (`SCryptPasswordEncoder`) | Scrypt by default in Werkzeug 3, with the method and salt in the stored string. The comparison is constant-time. |
| `django.test.Client` | `app.test_client()`, `app.test_cli_runner()` | `MockMvc` | Make a `client` fixture in `conftest.py` from `create_app(test_config)`. |

## Things that bite

- **Raw body for signatures.** Verify HMAC on `request.get_data()`, the exact bytes received, never on re-serialised JSON. Key order and whitespace would differ.
- **The two contexts.** The *app context* (`current_app`, `g`) and the *request context* (`request`, `session`). A CLI command or the worker has an app context but no request context.
- **`g` is not a cache.** It's gone after the request. Don't store anything there you need next time.
- **`debug=True` is not for production.** Run under gunicorn in Docker (`gunicorn "flightlog:create_app()"`).
- **`flask.session` is a signed cookie,** not server-side storage, and has nothing to do with the SQLAlchemy session. Don't mix them up in an interview answer.
- **A blueprint's 404/405 handler doesn't fire for unknown URLs.** `@bp.errorhandler(404)` only handles an `abort(404)` raised inside that blueprint's own views. When no route matches, Flask doesn't know which blueprint the URL was meant for (`request.blueprints` is `[]`), so `/ingest/nope` falls through to the app-level handler. Decide JSON vs. HTML there, by path prefix.
- **Autoescaping depends on the file extension.** Jinja escapes `{{ }}` in `.html`, `.xml` and `.htm` templates by default, but not in `render_template_string` or a `.txt` template. Untrusted text, like hook payloads, must only go through `.html` templates and never through `|safe`.
- **`app.config.setdefault()` does nothing for Flask's own keys.** `SESSION_COOKIE_SAMESITE`, `SESSION_COOKIE_SECURE` and `PERMANENT_SESSION_LIFETIME` are already in the default config, so `setdefault` keeps Flask's values. Set them with `config.update()` before `from_prefixed_env()`, so the environment can still override them. A cookie test caught this.
- **A session cookie isn't permanent unless you say so.** Without `session.permanent = True`, `PERMANENT_SESSION_LIFETIME` is ignored and the cookie lasts until the browser closes.

## Interview angles

- "Why an app factory?" Testability (a fresh app per test with its own config), no global state at import time, several configs side by side.
- "How do you manage the DB session in Flask?" One per request on `g`, closed in teardown; commit at the end of the unit of work, roll back on error.
- "Flask or Django?" Django when you want admin, auth and ORM out of the box. Flask when you integrate systems and want a small, explicit service, which is usually the case for middleware.

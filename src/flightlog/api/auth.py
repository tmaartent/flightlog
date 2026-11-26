"""The admin login and CSRF tokens for the HTML pages (ADR-0012).

Machines use API keys (ADR-0005); this is only for the person looking at the dashboard.
"""

import hmac
import secrets

import click
from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask.typing import ResponseReturnValue
from werkzeug.security import check_password_hash, generate_password_hash

bp = Blueprint("auth", __name__, cli_group=None)

CSRF_FIELD = "csrf_token"
UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def require_admin() -> ResponseReturnValue | None:
    """before_request for the dashboard and admin blueprints: log in first."""
    if session.get("admin") is True:
        return None
    if request.method in UNSAFE_METHODS:
        # Not a redirect: it would drop the POST anyway, and the audit log would read the 302
        # as "ok" (ADR-0015). A form posted after the session expired lands here.
        abort(401, "Log in first: your session has ended.")
    # full_path ends with "?" when there is no query string.
    return redirect(url_for("auth.login", next=request.full_path.rstrip("?")))


def csrf_token() -> str:
    """The session's CSRF token, made on first use. A template global: {{ csrf_token() }}."""
    if not current_app.secret_key:
        return ""  # no session without a secret key; the login page says what's missing
    if CSRF_FIELD not in session:
        session[CSRF_FIELD] = secrets.token_urlsafe(32)
    return session[CSRF_FIELD]


def check_csrf() -> None:
    """before_request for every blueprint with HTML forms: an unsafe method needs the token.

    The synchroniser-token pattern: the token lives in the signed session and in the form.
    Another site can make the browser send the cookie, but it can't read the token.
    """
    if request.method not in UNSAFE_METHODS:
        return
    expected = session.get(CSRF_FIELD)
    sent = request.form.get(CSRF_FIELD, "")
    if not expected or not hmac.compare_digest(expected, sent):
        abort(400, "CSRF token missing or invalid. Reload the page and try again.")


bp.before_request(check_csrf)


@bp.app_context_processor
def template_globals() -> dict:
    return {"csrf_token": csrf_token, "is_admin": session.get("admin") is True}


@bp.route("/login", methods=["GET", "POST"])
def login() -> ResponseReturnValue:
    password_hash = current_app.config.get("ADMIN_PASSWORD_HASH")
    configured = bool(password_hash and current_app.secret_key)
    next_url = safe_next(request.args.get("next"))

    if request.method == "POST":
        password = request.form.get("password", "")
        if configured and check_password_hash(password_hash, password):
            # A fresh session: nothing planted before login carries over (session fixation).
            session.clear()
            session.permanent = True
            session["admin"] = True
            return redirect(next_url)
        flash("Wrong password." if configured else "Login is not configured.", "error")
        return render_template("auth/login.html", configured=configured, next=next_url), 401

    return render_template("auth/login.html", configured=configured, next=next_url)


@bp.post("/logout")
def logout() -> ResponseReturnValue:
    session.clear()
    return redirect(url_for("auth.login"))


def safe_next(target: str | None) -> str:
    """Only a path on this site: "/x" yes; "//evil", "https://evil" or "/\\evil" no.

    Browsers read "/\\evil.example" as "//evil.example", another host, so a backslash is out.
    """
    if target and target.startswith("/") and not target.startswith("//") and "\\" not in target:
        return target
    return url_for("dashboard.sessions")


@bp.cli.command("hash-password")
@click.password_option(help="The admin password; asked for twice when left out.")
def hash_password(password: str) -> None:
    """Print a hash of the admin password, for FLASK_ADMIN_PASSWORD_HASH."""
    click.echo(generate_password_hash(password))

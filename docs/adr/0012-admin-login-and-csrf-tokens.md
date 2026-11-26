# 0012 · A single admin login and hand-written CSRF tokens

- Status: Accepted
- Date: 2026-11-26
- Carries out: [ADR-0011](0011-no-access-control-for-the-dashboard-yet.md)

## Context
M3 task 3 adds the first state-changing page: a "retry" button for failed jobs. ADR-0011 set the deadline for a login at that point, with CSRF tokens on every POST. Flightlog has one person looking at it, and machines already have their own credential (API keys, ADR-0005).

## Decision
- **One admin, no user table.** The password is configured as a hash, `FLASK_ADMIN_PASSWORD_HASH`, made with `werkzeug.security.generate_password_hash` (scrypt, ships with Flask) through `flask hash-password`. Plain text is never stored or configured, and `check_password_hash` compares in constant time.
- **A `flask.session` cookie** marks the browser as logged in. It's signed with `FLASK_SECRET_KEY` and set with `HttpOnly`, `SameSite=Lax`, a 12-hour lifetime, and `Secure` unless the app runs in debug mode. Login clears the old session first, so a session id planted before login isn't kept (session fixation).
- **One guard** (`require_admin`) runs as `before_request` on the `dashboard` and `admin` blueprints. Anonymous requests are redirected to `/login?next=<path>`. `next` is followed only when it is a local path (`/…`, not `//…` and no backslash), so the login page can't be used as an open redirect.
- **Synchroniser-token CSRF, written by hand:** a random token per session (`secrets.token_urlsafe(32)`), rendered as a hidden `csrf_token` field by the `csrf_token()` template global and compared with `hmac.compare_digest` before any POST, PUT, PATCH or DELETE on the HTML blueprints (`auth`, `dashboard`, `admin`). A missing or wrong token is a 400. Logout is a POST with the token too, so another site can't log you out. `/ingest` and `/api` don't use cookies, so they have no CSRF check.
- **Retry resets the failed job in place:** `failed_at = NULL`, `attempts = 0`, `available_at = now()`, keeping `last_error` until the next run overwrites it or deletes the job. One job per click, no "retry all".

Alternatives considered: Flask-Login (user objects and a user loader for one account that has no other data), Flask-WTF's `CSRFProtect` (a dependency, and it guards `/ingest` too unless exempted), and the double-submit cookie pattern (stateless, but weaker than a token in the signed session when a subdomain can set cookies).

## Consequences
- **Two secrets more to configure:** `FLASK_SECRET_KEY` and `FLASK_ADMIN_PASSWORD_HASH`. Without them the login page says that login isn't configured, instead of failing with a 500.
- **No lockout yet.** Brute-forcing the login is slowed only by scrypt. Flask-Limiter (M4) gets a limit on `POST /login`.
- **Changing `SECRET_KEY` logs everyone out,** which is also the way to end every session at once.
- **Admin actions aren't audited yet;** the audit log (M4, ADR-0014) adds login, logout and retry.
- **`SameSite=Lax` already blocks cross-site POSTs** in current browsers. The token is still needed for older browsers and for same-site attacks from another app on `localhost`.

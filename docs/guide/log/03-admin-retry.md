# 03 · Admin login, CSRF and retrying failed jobs (M3, task 3)

Branch `feat/admin-retry`, stacked on `feat/dashboard`. Decision record: [ADR-0012](../../adr/0012-admin-login-and-csrf-tokens.md).

## What was built
- **Login** (`api/auth.py`): one admin, a scrypt password hash from config (`flask hash-password` makes one), and a `flask.session` cookie (`HttpOnly`, `SameSite=Lax`, `Secure` outside debug, 12 hours). `require_admin` guards the `dashboard` and `admin` blueprints and redirects to `/login?next=…`. Only local paths are followed after login.
- **CSRF**: a per-session token, a hidden field on every form, and `check_csrf` comparing them with `hmac.compare_digest` on POST, PUT, PATCH and DELETE. Logout is a POST too.
- **Retry**: `JobQueue.retry_now(job_id)` is one guarded `UPDATE … WHERE failed_at IS NOT NULL`, so a double click or a pending job changes nothing. `JobQueries.failed_jobs()` lists failed jobs with their event. The use case `retry_failed_job` commits.
- **Admin page** `/admin/jobs`: failed jobs, their last error, and a Retry button per job, with Post/Redirect/Get and a flash message.
- **Tests**: 286 in total (+43), including 4 new browser tests: login with a return to the page, logout, retry followed by the worker (the last M3 acceptance criterion), and a forged CSRF token refused from a logged-in browser.

## What I learned
- **Check the framework's defaults before `setdefault`.** Flask's default config already holds `SESSION_COOKIE_SAMESITE` (None) and a 31-day lifetime, so `setdefault` kept them. The cookie test failed and showed it.
- **Session fixation.** Clearing the session at login means an id or values planted before login don't carry over into the logged-in session.
- **Open redirects through `next`.** `//evil.example` and `/\evil.example` both start with a slash, but browsers read them as another host.
- **CSRF and SameSite are layers.** `SameSite=Lax` already stops cross-site POSTs in current browsers; the token covers older browsers and same-site attackers, such as another app on `localhost`.
- **A conditional UPDATE is an idempotency guard.** `WHERE id = :id AND failed_at IS NOT NULL` with `rowcount == 1` makes a retry safe to repeat, without a read-then-write race.

## Open questions
- **No limit on login attempts yet;** M4's Flask-Limiter adds one on `POST /login`.
- **Admin actions aren't audited yet;** M4's audit log adds login, logout and retry.
- **No "retry all"** for when a deploy fixed many jobs at once. Add it if that actually happens.

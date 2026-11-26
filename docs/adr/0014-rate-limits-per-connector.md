# 0014 · Rate limits per connector, with Flask-Limiter

- Status: Accepted
- Date: 2026-11-26
- Builds on: [ADR-0005](0005-api-keys-per-connector.md), [ADR-0012](0012-admin-login-and-csrf-tokens.md)

## Context
M4 task 2: the read API gets rate limits keyed on the connector, not the IP, so clients behind one NAT don't share a budget and one busy script can't starve the others. ADR-0012 also promised a limit on `POST /login`, since scrypt alone only slows guessing down.

Flask-Limiter 4.1 checks limits in an **app-level** `before_request` (registered in `init_app`). Flask runs app-level hooks before blueprint hooks, so the limiter's key function runs before the API's `require_api_key`, when `g.connector` isn't set yet.

## Decision
- **The connector is looked up lazily.** `current_connector()` (now in `api/bearer.py`, shared with the audit log) authenticates the Bearer key the first time something asks and caches the result on `g`, `None` included. The limiter's key function and `require_api_key` both call it. The hook order no longer matters, and the database is still queried once per request. Rejected: calling `limiter.check()` by hand after authentication (the extension's middleware has to be switched off for that blueprint), and registering our own app-level hook before the limiter's (correct only as long as nobody reorders `create_app`).
- **Buckets:** `connector:<id>` for a valid key (the id, so a renamed connector keeps its bucket), and `ip:<addr>` for a missing, wrong or revoked key, with a lower limit to slow down key guessing. Such a request is still a 401 until it passes the limit, then a 429.
- **Limits from config,** so tests can set `3 per minute` and production can change them from the environment (`FLASK_RATELIMIT_…`):

  | Key | Default | Bucket |
  | --- | --- | --- |
  | `RATELIMIT_API` | `120 per minute` | per connector |
  | `RATELIMIT_API_ANONYMOUS` | `20 per minute` | per IP |
  | `RATELIMIT_LOGIN` | `5 per minute; 20 per hour` | per IP, `POST /login` only |

- **One shared bucket for the whole API** (`shared_limit(..., scope="read_api")` on the blueprint). A plain `limit` on a blueprint gives every endpoint its own bucket.
- **Strategy `sliding-window-counter`.** A fixed window lets a client send twice the limit across the edge of a window; a moving window keeps a timestamp for every hit.
- **A 429 is JSON on `/api`:** `{"error": "rate limit exceeded: 120 per 1 minute"}` with `Retry-After` in seconds, through `api/errors.py`. `RATELIMIT_HEADERS_ENABLED` also sends `X-RateLimit-Limit`, `-Remaining` and `-Reset`, but only on limited routes.
- **Nothing else is limited:** no default limits, so `/ingest`, `/health` and the dashboard stay unlimited. GitHub handles a 429 on webhooks poorly, and the HMAC check already refuses strangers cheaply. Logout (also a POST on `auth`) is exempt.
- **Storage `memory://`** by default (`RATELIMIT_STORAGE_URI`). The `Limiter` is created per app in `api/rate_limits.init_app`, so every test app starts with empty counters. `limits` has no PostgreSQL backend.

## Consequences
- **Counters are per process** (in compose since ADR-0017 they are in Redis). With 4 gunicorn workers a connector can get up to 4× its limit, and a restart resets every counter. Task 6 (Docker) decides on Redis as a compose service (`RATELIMIT_STORAGE_URI=redis://…`): no code change, only the `redis` extra of `limits` as a dependency.
- **Behind a reverse proxy every request has the proxy's IP,** so the per-IP buckets become one. Task 6 needs `ProxyFix` when there is a proxy in front.
- **The e2e suite** shares one live server and logs in more than 5 times a minute, so its app sets `RATELIMIT_LOGIN` high.
- **Over the login limit, even the right password gets a 429** until the window has passed. The 429 comes before the password check, so it says nothing about the password.

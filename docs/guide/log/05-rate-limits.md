# 05 · Rate limits per connector (M4, task 2)

Branch `feat/rate-limits`. Decision record: [ADR-0014](../../adr/0014-rate-limits-per-connector.md).

## What was built
- **`api/rate_limits.py`**: one `Limiter` per app, with config defaults applied after `from_prefixed_env`. Two limits:
  - a **shared** limit on the `read_api` blueprint, keyed `connector:<id>`, or `ip:<addr>` with a lower limit when there's no valid key;
  - a limit on `POST /login` per IP, with logout exempt.
- **`read_api.current_connector()`**: authenticates once per request and caches the result on `g`, so the limiter and `require_api_key` share one lookup.
- **429s are JSON on `/api`**, with `Retry-After` and `X-RateLimit-*` headers.
- **Tests**: 355 in total (+10). Without the limiter wired in, 7 of the 10 fail; the other 3 check routes that must stay unlimited.

## What I learned
- **Hook order.** App-level `before_request` functions run before blueprint ones, and Flask-Limiter registers its check at the app level. Anything a key function needs must therefore be computed lazily, not by a blueprint hook.
- **`limit` vs `shared_limit` on a blueprint.** `limit` makes one bucket per endpoint (the scope includes the endpoint); `shared_limit` makes one bucket for all of them.
- **Strategies.**
  - A fixed window allows 2× the limit across a window's edge.
  - A moving window is exact but stores every hit.
  - A sliding-window counter weights the previous window's count, so it's nearly exact with two counters.
- **In-memory counters are per process,** which matters as soon as gunicorn runs more than one worker.

## Open questions
- **Redis in task 6?** Needed for correct limits with several workers. Cheap as a compose service.
- **`ProxyFix`** once something sits in front of the app, or every client shares one IP bucket.

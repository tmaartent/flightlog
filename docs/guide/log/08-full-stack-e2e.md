# 08 · End to end across processes (M4, task 5)

Branch `test/full-stack-e2e`. Decision record: [ADR-0013](../../adr/0013-playwright-against-a-live-server-on-its-own-database.md), section "The full stack".

## What was built
- **`tests/e2e/stack.py`**: starts `flask run` as a subprocess on a free port, configured only through `FLASK_*` variables, and waits for `/health`. `flask(*args)` runs other CLI commands as processes; `send_hook(event)` runs `scripts/flightlog_hook.py` with the event on stdin.
- **`tests/e2e/test_full_stack.py`**, two journeys:
  - hook script, then worker, then dashboard, with the branch read from a real git checkout;
  - `flask connector create`, then the read API over HTTP, then `/admin/audit` in the browser.
- **The e2e `TRUNCATE`** now empties `connectors` and `audit_log` too. **`E2E_DATABASE_URL`** moved to `tests/harness.py`, so tests can import it without loading `conftest.py` twice.
- **A report hook in the e2e conftest**: a failed full-stack test prints the server's log.
- **Tests**: 432 in total (+2). With the worker step removed, the first journey fails, as it should.

## What I learned
- **The threaded live server can't test configuration.** It shares the test's app object. Only a separate process proves that `from_prefixed_env()` and the environment are enough to run Flightlog.
- **`FLASK_SKIP_DOTENV=1`.** The `flask` command loads `.env` itself. In a test that would quietly point the server at the dev database.
- **A "never fail" client needs a different check.** The hook script always exits 0, so the test asserts on the status it prints, and on the session reaching the dashboard.
- **Output from a subprocess is lost unless you keep it.** A log file, plus `pytest_runtest_makereport` to know a test failed, gives the server's traceback next to the failure.

## Open questions
- **Task 6:** run the same two journeys against `docker compose` instead of `flask run`, with a switch such as `E2E_STACK=compose`.

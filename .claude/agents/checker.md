---
name: checker
description: Runs Flightlog's checks (ruff, format, import layers, pytest, alembic) and reports only what fails. Use for a quick "is everything green?".
tools: Bash, Read
model: haiku
---

Run, from the repo root:

```bash
source .venv/Scripts/activate
ruff check .
ruff format --check .
lint-imports
pytest -q
alembic check
```

Run all of them, even if one fails. Report one line per check: passed, or failed with the essential error (failing test names and the assertion, the ruff rule and file:line, the broken import contract). If PostgreSQL isn't reachable, say "database down: run `docker compose up -d db`". Do not fix anything and do not edit files.

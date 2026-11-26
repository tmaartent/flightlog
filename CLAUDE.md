# Working agreement for Claude

This is a **learning project** for Flask, SQLAlchemy 2, Alembic, webhook handling and Playwright. Since 2026-11-26 **Claude builds and the owner reviews**: the goal is a finished Flightlog (M3 and M4, then M5 in `docs/plan.md`), with the interesting choices written down so the owner learns from them.

## Role: builder, owner reviews

- **Claude writes the code in `src/` and `tests/`**, test-first, following the layers and conventions below.
- **Keep the choices doc:** every notable Flask, Python, SQLAlchemy or Playwright choice gets a row in the "Flightlog: Flask and Python choices" doc (https://claude.ai/artifact/9mjzNw9nzL8KhYM7qHjzK5): what was chosen, instead of what, why, and the Django/Spring equivalent.
- **Grill before deciding.** Design choices are still the owner's: settle them in grilling rounds (numbered questions, each with a recommended answer) before building, and record each decision as an ADR in `docs/adr/`.
- **Delivery:** one branch and PR per milestone task, Conventional Commits. Claude opens the PR; the owner reviews and gives the OK before it is merged.
- **Owner's background:** experienced with Python (Django), Java/Spring, TypeScript, PostgreSQL, Docker, DDD and TDD. New to Flask and Playwright. Explain Flask by mapping it to Django (and Spring where it helps); keep `docs/guide/flask-for-django-devs.md` up to date with every new mapping. Don't re-explain TDD, DDD or Docker.
- **Reviews:** rank findings: correctness of the event handling (signatures, idempotency, ordering) first, then tests, then API/contract, then style. Explain *why* something is a problem, and name the interview-relevant concept behind it.
- **Verify library APIs against the installed version** (`pip show <pkg>`, the release docs) before suggesting a method. Flask 3.1, SQLAlchemy 2.1, Alembic 1.20, Flask-Limiter 4, Playwright 1.65.
- **After each task**, write a short log in `docs/guide/log/NN-<task>.md`: what was built, what was learned, open questions. The owner may ask Claude to draft it from the diff.

## Agent roles

Subagents in `.claude/agents/`, each on the model that fits the work. The main session stays the mentor and delegates when a task is self-contained:

| Agent | Model | Use for |
|---|---|---|
| `architect` | Opus | A design choice: options, recommendation, then the ADR. Writes only under `docs/`. |
| `reviewer` | Opus | "Check my work": ranked findings with the why, verified, no fixes. |
| `implementer` | Sonnet | Only when the owner hands work over ("you finish up"). Follows the agreed design. |
| `checker` | Haiku | "Is everything green?": runs ruff, lint-imports, pytest, alembic check. |
| `scribe` | Sonnet | The log in `docs/guide/log/` and the Flask-for-Django guide. |

Questions and short explanations stay in the main session: a subagent starts cold, so it only pays off for a task that stands on its own.

## Project conventions

- Plan and acceptance criteria: `docs/plan.md`. Decisions: `docs/adr/`.
- Layers (ADR-0007), enforced by `lint-imports` in CI:
  - `domain/`: entities and their rules as plain dataclasses. No Flask, no SQLAlchemy.
  - `contracts/`: commands in, results out (frozen dataclasses).
  - `application/`: use cases; reach the outside world only through the Protocols in `ports.py`.
  - `infrastructure/`: SQLAlchemy tables, imperative mapping, repositories, unit of work, request session.
  - `api/`: Flask blueprints and CLI; never imports infrastructure (adapters come from `app.extensions`).
  - `__init__.py`: `create_app`, the composition root that wires the layers together.
- Other folders: `tests/` (one subfolder per layer), `migrations/` (Alembic, against `infrastructure.tables.metadata`), `scripts/` (the hook client), `client/` (`flightlog-client`, the typed read API client: its own package, standard library only, ADR-0020).
- SQLAlchemy 2 style: `Table` definitions in `infrastructure/tables.py`, imperative mapping onto the domain classes, `select()` queries, no legacy `Query` API.
- Every schema change is an Alembic migration, reviewed by hand. Autogenerate is a draft, never the final word.
- Tests: pytest. Domain and application tests without Flask or a database (fakes for the ports); infrastructure and API tests against a real PostgreSQL (docker compose); Playwright for end-to-end.
- Commits: Conventional Commits (`feat(ingest): verify GitHub signatures`). No AI co-author lines.

## Commands

```bash
docker compose up -d db                 # PostgreSQL on localhost:5433
python -m venv .venv && .venv/Scripts/activate
pip install -e ".[dev]" -e client && playwright install chromium
alembic upgrade head
flask --app flightlog run --debug       # http://localhost:5000
docker compose up -d --build --wait     # the whole stack in containers, http://localhost:8000
flask --app flightlog sessions --last 5 # what earlier sessions in this repo did
flask --app flightlog mcp               # the read-only MCP server (Claude Code starts it from .mcp.json)
pytest
ruff check . && ruff format --check .
```

## Agent skills

### Issue tracker

Issues and milestones live in GitHub Issues (`tmaartent/flightlog`), managed with `gh`. See `docs/agents/issue-tracker.md`.

### Triage labels

Default vocabulary: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: `GLOSSARY.md` at the root (created lazily) and ADRs in `docs/adr/`. See `docs/agents/domain.md`.

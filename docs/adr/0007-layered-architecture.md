# 0007 · Layered architecture with a framework-free domain

- Status: Accepted
- Date: 2026-11-15

## Context
The first version put HTTP handling, signature checks and SQL in one module, and the models were SQLAlchemy classes. The worker (M2, step 4) brings real domain rules: a session's `started_at` only moves earlier, `ended_at` only later, and its status only forward, so events can be applied in any order. Those rules would have ended up as SQL inside a CLI command, testable only with Flask and PostgreSQL running.

## Decision
Five layers, each importing only the layers below it:

| Layer | Holds | May import |
| --- | --- | --- |
| `api` | Flask blueprints, CLI, signature checks, translating requests into commands | application, contracts, domain |
| `infrastructure` | SQLAlchemy tables, imperative mapping, repositories, unit of work, request session | application (ports), contracts, domain |
| `application` | use cases, and ports (`Protocol`s) for everything outside | contracts, domain |
| `contracts` | commands and results (frozen dataclasses) | domain |
| `domain` | entities and their rules (plain dataclasses) | nothing |

- `api` and `infrastructure` are siblings: the API never imports infrastructure. `create_app` is the composition root; it puts the adapters (unit of work, database probe) in `app.extensions`.
- **Imperative mapping** (`registry.map_imperatively`): the tables live in `infrastructure/tables.py` and are mapped onto the domain dataclasses. The domain doesn't know SQLAlchemy exists, and there is still one class per concept. Alembic compares against `tables.metadata`.
- Entities are `@dataclass(eq=False)`: equal by identity, not by their current values.
- **Enforced** by import-linter (`lint-imports` in CI): a layers contract, and a forbidden contract that keeps Flask, SQLAlchemy, Alembic and psycopg out of domain, contracts and application.

Alternatives considered: separate ORM models with mappers to and from the domain (purest, but every concept twice plus conversion code), and keeping declarative models as the domain (least work, but the domain depends on SQLAlchemy).

## Consequences
- Domain rules and use cases are tested without Flask or a database, with fakes for the ports.
- Adding a use case means a command in `contracts`, a function in `application`, and only then a route in `api`.
- Columns the database fills (`received_at`) are mapped but not part of the domain classes; leaving them out of the constructor is what lets the server default apply.
- A little more ceremony than a plain Flask app. For a service that integrates several systems and has real rules, that is the point.

# 0002 · Plain SQLAlchemy 2 with a session per request

- Status: Proposed
- Date: 2026-11-12

## Context
Flask has no ORM of its own. The usual choices are Flask-SQLAlchemy (an extension that wires the session to the app context) or plain SQLAlchemy with your own wiring. Migrations: Flask-Migrate (a thin wrapper) or Alembic directly.

## Decision
Plain SQLAlchemy 2 (typed `Mapped[...]` models, `select()`) and Alembic directly. One session per request: created lazily and stored on `flask.g`, closed in `teardown_appcontext`. The worker opens its own session per batch.

## Consequences
- You see and own the wiring that Flask-SQLAlchemy hides: the app context, `g`, teardown. That is the knowledge that transfers to any Flask codebase.
- Slightly more code than Flask-SQLAlchemy. Switching later is easy: the models stay the same.

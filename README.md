# Flightlog

A flight recorder for coding agents.

Coding agents are fast, and it's easy to lose track of what they did. Flightlog receives events from Claude Code hooks and GitHub webhooks, stores them, and turns them into a timeline per agent session, linked to the branch and pull request the session produced. Once a week it renders a PDF report: sessions, tools used, files touched, test runs, and which PRs were merged or reverted.

```
Claude Code hooks ──► hook client (HMAC-signed) ──┐
GitHub webhooks (pull_request, push) ─────────────┴──► POST /ingest/<source>
                                                         verify · store · 202
                                                              │
                                                  worker: link session ↔ branch ↔ PR
                                                              │
                              dashboard (timeline) ◄──────────┤
                              weekly PDF report ◄─────────────┘
```

## What it shows

- **Webhook handling done properly:** signature verification, store-then-acknowledge, idempotency on delivery ids, events that arrive out of order or twice.
- **Flask** with an app factory and blueprints, **SQLAlchemy 2** and hand-reviewed **Alembic** migrations on **PostgreSQL**.
- **A small, secure read API:** an API key per connector (stored hashed), rate limiting, an audit log.
- **Playwright** for end-to-end tests and for rendering the report to PDF with headless Chromium.
- **Docker Compose** for the whole stack.

## Status

Work in progress. See [the plan](docs/plan.md) and the [decision records](docs/adr/).

## Running it

```bash
docker compose up -d db
python -m venv .venv && source .venv/Scripts/activate   # Windows Git Bash; use bin/ on Linux/macOS
pip install -e ".[dev]" && playwright install chromium
cp .env.example .env
alembic upgrade head
flask --app flightlog run --debug
```

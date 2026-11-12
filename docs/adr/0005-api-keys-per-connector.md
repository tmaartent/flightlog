# 0005 · API keys per connector

- Status: Proposed
- Date: 2026-11-12

## Context
The read API is used by more than one client (a script, a dashboard elsewhere). One shared key can't be revoked for one client, and logs can't tell clients apart.

## Decision
Each connector gets its own key: `fl_<prefix>_<secret>`. Only a SHA-256 hash and the prefix are stored; the full key is shown once at creation. Requests send `Authorization: Bearer <key>`. Rate limits and audit rows are keyed on the connector.

## Consequences
- One leaked key is revoked without touching the others.
- A plain SHA-256 is fine here because the keys are long and random; passwords would need a slow hash.

# 0004 · Idempotency and ordering

- Status: Proposed
- Date: 2026-11-12

## Context
Webhooks arrive at least once, not exactly once: GitHub redeliveries reuse the same delivery id, and our hook client may retry. They also arrive out of order: a `Stop` can overtake the last `PostToolUse`.

## Decision
- A unique constraint on `(source, delivery_id)`. A duplicate insert is caught and answered with 200.
- Processing is idempotent: applying the same event twice leaves the same state.
- Session state is derived from each event's `occurred_at`, never from arrival order. A late event is still added to the timeline; `ended_at` is the latest `Stop`, not the last one received.

## Consequences
- Retries are always safe, from any side.
- The state machine needs tests for every out-of-order combination that matters.

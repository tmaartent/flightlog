# 0008 · A separate job table, deleted on success

- Status: Accepted
- Date: 2026-11-15
- Supersedes: the "the queue is the event table itself" part of [ADR-0003](0003-store-then-acknowledge.md)

## Context
ADR-0003 made the event table the queue. That mixes facts (what happened) with processing state (attempt 3, last error), makes the table grow forever, and leaves no room for more than one kind of work per event (applying it to a session now, linking a PR or writing a summary later).

## Decision
- **`event_jobs`** holds the work: `event_log_id`, `kind`, `attempts`, `available_at`, `last_error`, `failed_at`, `created_at`. Unique on `(event_log_id, kind)`.
- **Ingest writes the event and its job in one transaction**, through the unit of work. There is no moment where an event exists without its job. This is the transactional outbox idea, and it is why there is no broker: no dual write, so no lost events.
- **A row's existence means pending.** A finished job is **deleted**. `failed_at` marks a job given up on; those stay visible so they can be retried by hand.
- **Due** = `failed_at IS NULL AND available_at <= now()`, using the database's clock. A plain index on `available_at` is enough: finished jobs are gone, so there is no mass of done rows to leave out with a partial index.
- **Claiming:** `FOR UPDATE SKIP LOCKED`, **one job per transaction**: claim, apply, delete, commit. `SKIP LOCKED` only skips rows locked by *other* transactions, so a worker that claims twice in one transaction gets its own job back.
- **On error:** roll back, then record the failure (`attempts`, `last_error`, `available_at` = now + backoff, or `failed_at` after the last attempt) in a separate transaction.
- **At-least-once:** a job can run twice (a crash after applying, before the commit), so every job handler is idempotent.

## Consequences
- `event_logs` stays an append-only record; adding a kind of work never touches it.
- A busy queue table with many deletes creates dead tuples; autovacuum handles that at this volume.
- Not covered yet: a job that crashes the worker process itself never gets its attempt recorded, because that update rolls back too. The remedy, recording the attempt in its own transaction before processing (a lease), is noted for higher volumes.

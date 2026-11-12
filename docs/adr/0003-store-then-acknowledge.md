# 0003 · Store, then acknowledge, then process

- Status: Proposed
- Date: 2026-11-12

## Context
Webhook senders time out quickly (GitHub after 10 seconds) and retry or give up. Processing in the request makes the sender wait, and a crash halfway loses the event.

## Decision
The ingest route only verifies the signature, stores the raw event and returns 202. A separate worker processes stored events. The queue is the `event` table itself: the worker claims rows with `SELECT … FOR UPDATE SKIP LOCKED`, so several workers can run without a broker.

## Consequences
- Nothing is lost once it's acknowledged, and the sender never waits on our logic.
- Processing is asynchronous, so the dashboard can lag a few seconds.
- No RabbitMQ or Redis needed. If volume ever demands it, the worker can move to a broker without changing the ingest route.

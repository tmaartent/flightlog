# 0018 · Stored session summaries, computed by the worker

- Status: Accepted
- Date: 2026-11-26
- Builds on: [ADR-0004](0004-idempotency-and-ordering.md), [ADR-0008](0008-job-table-deleted-on-success.md), [ADR-0009](0009-link-sessions-to-pull-requests-at-read-time.md), [ADR-0010](0010-dashboard-read-models-and-session-timeline.md)

## Context
M5 task 1: a summary per finished session, as structured data, stored so it's computed once. The plan's rules: structured output only, never raw transcript or tool text (old sessions hold content from web pages and files, and feeding it back to an agent would bring injected instructions with it), and no secrets. The acceptance criterion: every finished session has a stored summary, and a test shows it holds no raw tool input.

Two facts from earlier ADRs shape it. Events arrive out of order, so one can land after `SessionEnd` (ADR-0004). PR outcomes change after the session (merged, later reverted) and are linked at read time (ADR-0009).

## Decision
- **Called a digest in the code** (`SessionDigest`, table `session_digests`), because `SessionSummary` already names a row of the session list.
- **Stored:** the files touched (relative to the repo), edits to files outside it (a count), edits, test runs, tool calls, calls per tool, duration, the number of events it was computed from, and the rules version. Counted with the timeline's `classify`, so dashboard, report and digest agree.
- **Not stored:**
  - **The PR outcome.** It changes later, so it's joined at read time like everywhere else.
  - **The goal.** It is the linked PR's title, or else the branch name, also at read time (M5 task 2).
  - **Prompts, commands, file content, URLs and tool responses.** The repository selects only `tool_name`, `file_path`/`notebook_path`, `command` and `cwd` from the payload. The command is used to recognise a test run and then dropped.
- **Paths relative to the session's `cwd`.** A path outside it is counted, not named. Home directories and user names stay out, and paths line up across machines. Windows paths are compared without case.
- **A job kind, `summarize_session`.** `apply_to_session` enqueues it in its own transaction whenever the session it just applied to is stopped: on `SessionEnd`, and for every late event after it. It is keyed on the triggering event (the existing unique `(event_log_id, kind)`), so a second run of `apply_to_session` (which returns early for a processed event) can't queue it twice.
- **A conditional upsert against lost updates.** Two summarize jobs for one session can run at once, and the one that read fewer events may finish last. Events are never deleted, so a digest from more events is newer. `INSERT … ON CONFLICT (agent_session_id) DO UPDATE … WHERE (new.rules_version, new.event_count) >= (stored.rules_version, stored.event_count)` keeps the newest, in one statement.
- **`rules_version`** (now 1) is bumped when the counting rules change. `flask summaries rebuild` queues a job (`enqueue_unless_queued`: `ON CONFLICT DO NOTHING`) for every stopped session without a digest of the current version, using its latest event. That is also the backfill for sessions from before this release; the migration computes nothing.
- **A line written by the Claude API** waits for a task of its own. It sends session data to an outside service and needs a key and a cost limit, and its input would have to be the digest, not the events.

## Consequences
- After `SessionEnd`, a digest exists once the worker has run its next job. An active session has none.
- One more job per finished session and per late event: a scan of that session's events.
- The digest is only as current as its rules. After a rules change, `flask summaries rebuild` and the worker bring it up to date.
- Nothing reads the digests yet. M5 task 2 (`flask sessions`) and the MCP tools will.

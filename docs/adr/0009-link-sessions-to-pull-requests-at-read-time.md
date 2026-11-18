# 0009 · Link sessions to pull requests at read time, on repo and branch

- Status: Accepted
- Date: 2026-11-17

## Context
M3 shows what came of an agent session: the pull request opened from its work, and whether that PR was merged or reverted. A Claude Code hook knows the session and its `cwd`, but nothing about git or GitHub. A GitHub delivery knows the PR, but nothing about sessions. The two only meet on the branch, and they arrive in any order: the PR can be opened before the session's last event, or long after it ended.

## Decision
- **The hook client adds the branch.** `scripts/flightlog_hook.py` runs `git rev-parse --abbrev-ref HEAD` in the hook's `cwd`, with a 1 s timeout, and puts the result in the signed envelope as `git.branch`. A detached HEAD, a folder that isn't a repository, a missing git or a timeout gives `None`, never an error.
- **The latest event's branch wins.** `AgentSession.record` takes the branch and keeps it only when the event is newer than `branch_seen_at`. The agent may switch branches; the one it ends on is the one its PR comes from.
- **`PullRequest` is its own aggregate** in `pull_requests`, unique on `(repo, number)`, kept up to date by a separate job kind, `apply_pull_request`. It changes without any session, and can fail without holding up session updates. The newest snapshot (by GitHub's `pull_request.updated_at`) wins, except that merged is final.
- **The link is a query, not a stored foreign key.** `AgentSessionQueries.linked_pull_requests` joins sessions and PRs on `(repo, branch)`. Nothing has to be re-linked when the PR or the session arrives late, and the `LINKED` session status is dropped.
- **"Reverted" is derived too.** A PR records the number it reverts, parsed from GitHub's "Reverts owner/repo#N" body. A merged PR is shown as reverted when a merged PR in the same repo `reverts` it: an `EXISTS` on `(repo, reverts)`.
- **Which work an event needs** is decided by `jobs_for(source, type)`: Claude events → `apply_to_session`, GitHub `pull_request` → `apply_pull_request`, anything else → no job.

## Consequences
- Order no longer matters for linking: the join gives the same answer whichever side arrived first.
- Events without a job (GitHub `push`, for now) are recorded, but their `processed_at` stays NULL. "Unprocessed" therefore doesn't mean "pending"; a pending job is a row in `event_jobs` (ADR-0008).
- Repos are matched by their bare name: `repository.name` from GitHub, the last folder of `cwd` from the hook. Two repos with the same name under different owners, or a clone in a renamed folder, would mix or miss links. Good enough for one developer; storing the remote's `owner/name` from the hook client fixes it later.
- A branch name is reused over time (`main`, or a branch recreated after deletion), so a session can show PRs from before or after it. Showing all of them, oldest first, is honest; narrowing by time is possible once that confuses someone.
- Reverts made by hand, without GitHub's body text, are not detected.
- Sessions from before M3 have no branch and stay unlinked.

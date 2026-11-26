# 0016 · The weekly report: one A4 page per repo, rendered in-process

- Status: Accepted
- Date: 2026-11-26
- Builds on: [ADR-0006](0006-playwright-for-e2e-and-pdf.md), [ADR-0009](0009-link-sessions-to-pull-requests-at-read-time.md), [ADR-0010](0010-dashboard-read-models-and-session-timeline.md)

## Context
M4 task 4: `flask --app flightlog report --week 2026-W46` writes a PDF. The acceptance criterion is "the report PDF exists and has one page per repo". ADR-0006 already chose Playwright and headless Chromium for the PDF. Still to decide: how the HTML reaches Chromium, what a page holds, which week is meant, and how a busy repo still fits on one page.

## Decision
- **The week is an ISO 8601 week** (`2026-W46`), parsed with `date.fromisocalendar`. It runs from Monday 00:00 UTC up to the next Monday, and a session belongs to the week it **started** in. Without `--week`, the last full week. A bad value is a click error (CLI) or a 404 (preview).
- **The HTML is rendered in-process** and handed to Chromium with `page.set_content()`. There is no server and no login, and the network is blocked (`page.route("**/*", abort)`) with JavaScript off: the report needs neither, and an escaped path or branch name stays inert. The template inlines its CSS. `/reports/<week>` in the dashboard (behind the admin login) shows the same HTML, for working on the layout.
- **One page per repo,** sorted by name, each starting with `break-before: page`:
  - **summary:** sessions (stopped and active), time in stopped sessions, test runs, and pull requests by outcome, each PR counted once;
  - **the 10 most-edited files;**
  - **the sessions, newest first:** started, duration, branch, edits, test runs, and the newest linked PR.
- **The page has to fit, so it is designed to.** At most 20 session rows, then "And N more sessions, counted in the totals above". The tables use a fixed layout with one line per row; a long branch is cut with an ellipsis, and a long path is cut **at its start**, so the file name stays visible. The worst case, measured in Chromium at the printable A4 width, is 247 of 264 mm. A week without sessions is one page that says so. There is no cover page: the week and the generation time head every page.
- **Counts and paths only, never commands,** not even masked: a report is passed around. Edits and test runs are counted with the timeline's `classify`, so "test run" means the same in the dashboard, the API and the PDF.
- **Two queries per report, no N+1.** `ReportQueries.sessions_started(start, end)` returns sessions with their linked PRs (one SELECT each), and `events_of(ids)` returns their events. Both reuse the dashboard's SQL builders. The use case `weekly_report` groups and counts in Python.
- **`PdfRenderer` is a port.** `ChromiumPdfRenderer` in `infrastructure/pdf.py` launches Chromium per report and closes it. A4, 15 mm margins (18 mm at the bottom), `print_background`, and a footer "Flightlog · week · … · page X of Y" through `footer_template`. Tagged PDF and an outline (one bookmark per repo).
- **Tests:** the use case with fakes; the HTML through the preview; the CLI with a fake renderer; and one real-Chromium test that counts pages and reads their text with `pypdf` (a dev dependency). That test runs Playwright in its own thread, because pytest-playwright's sync Playwright already runs on the main one.

## Consequences
- `flask report` needs Chromium wherever it runs: CI and the Docker image (task 6) install it.
- Clipping hides the middle of very long names on paper. The full value is in the HTML preview (as a `title`), not in the PDF.
- A repo with more than 20 sessions a week loses detail on paper. If that becomes normal, a second page per repo would need a change to the acceptance criterion, not a smaller font.
- Chromium's page layout is the source of truth for "fits on one page". The real-PDF test is the guard; it caught a 3-page layout before the rows were made one line each.

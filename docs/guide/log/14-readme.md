# 14 · The README, with screenshots from Playwright

Branch `docs/readme`.

## What was built
- **A new README:**
  - why Flightlog exists and what it gives you, and its best features;
  - a tour of every page with screenshots;
  - the three agent interfaces, with real output;
  - how it works, the security model, getting started, configuration, a command reference, and the project layout.
- **`tests/e2e/screenshots.py`** (`python -m tests.e2e.screenshots`). It seeds a throwaway `flightlog_screenshots` database through the front door (signed hook events, GitHub deliveries, the worker, connector keys, API calls), serves the app on a free port, and saves a PNG per page to `docs/images/`. The data is fixed, so after a UI change only real differences show up.
- **A fix in the weekly report:** the "Started" column was 33 mm and cut off "UTC"; it's 37 mm now. The one-page PDF tests still pass.

## What I learned
- **Screenshots are a review.** Looking at the report on a page showed a truncated column that no test checked.
- **An HTML screenshot doesn't paginate.** `break-before: page` only applies when printing, so the report's image is the first repo's `<section>`, which is the PDF's first page.
- **Real output beats invented samples.** The README's `flask sessions`, MCP and client examples come from the same demo database as the screenshots.

## Open questions
- **The weekly report shows absolute paths** (`/work/flightlog/src/…`). It reads raw event paths, while the stored summaries are relative to the repo. A report that is passed around could then carry home-directory names. Reading the digests' relative paths would fix it.

# 0006 · Playwright for end-to-end tests and PDF rendering

- Status: Proposed
- Date: 2026-11-12

## Context
The report is an HTML page that has to become a PDF. The dashboard needs at least one test that goes through a real browser.

## Decision
Playwright for Python for both. The report is a Jinja template rendered by Flask; Playwright opens it in headless Chromium and calls `page.pdf()`. End-to-end tests use `pytest-playwright`.

## Consequences
- One tool, one browser, for tests and PDFs; the report looks exactly like the HTML.
- Chromium must be installed in CI and in the Docker image (`playwright install --with-deps chromium`), which makes the image bigger.

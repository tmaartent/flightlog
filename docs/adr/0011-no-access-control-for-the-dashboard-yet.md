# 0011 · No access control for the dashboard yet

- Status: Accepted
- Date: 2026-11-18

## Context
The dashboard (ADR-0010) shows commands, file paths and branches from agent sessions. For now it runs on one developer's machine: `flask run` binds to 127.0.0.1, and every dashboard page is a GET. Two things change that: M3 task 3 adds a "retry" button (a POST), and M4 runs the app in Docker with a published port. Security is M4's scope.

ADR-0005 already gives machines a credential: an API key per connector, sent as `Authorization: Bearer`. A browser does not send that header when someone opens a page or submits a form.

## Decision
- **No access control on the HTML pages for now.** The dashboard is read-only and bound to localhost.
- **Before M4's Docker exposure, or with task 3's first POST, whichever comes first,** the HTML pages get a session login: one admin password from config, stored as a slow hash, and a `flask.session` signed cookie, checked in a `before_request` on the dashboard and admin blueprints. Every state-changing POST then carries a CSRF token.
- **API keys stay for machines.** They are not reused for people.

## Consequences
- No auth code to write or test in this task.
- Until the login exists, anyone who can reach the port can read the dashboard. On 127.0.0.1 that is only this machine. A published Docker port without the login would be a leak; that is why the login has a deadline.
- Even on localhost, any web page open in the browser can send a form POST to `localhost:5000`. The retry button therefore must not ship without the CSRF token, even before the login exists.
- Why not the API keys: getting a bearer key into a browser means storing it in a cookie or in JavaScript, which turns it into a session login with extra steps and mixes human and machine identity in the audit log (M4). Cookies are sent by the browser on its own, so they need CSRF protection; bearer headers are not, so the API does not. Two mechanisms, each with the defence it needs.

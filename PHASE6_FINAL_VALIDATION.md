# Phase 6 final validation

**Phase 6 passed its local synthetic acceptance checks.** This is a development milestone, not approval to publish client websites or run live AI.

## Environment

- macOS local workspace, Python 3.13.16, Flask 3.1.3, SQLite from the Python runtime.
- Playwright 1.64.0 with Chromium 156.0.8078.4.
- Fresh temporary databases and fictional businesses/addresses. Existing customer databases were not opened or migrated.

## Executed results

| Check | Result |
|---|---|
| Complete unit/regression suite | **186 passed**, zero failures; 42.563 seconds |
| Phase 6 tests | 7 passed: accepted-brief build, one/multi-page output, two fictional industries, owner isolation, sandbox headers, markup escaping, QA blocking, version/revision/restore/approval, and mocked AI approval path |
| Real HTTP/server/worker smoke | Passed: Phase 3/4/5 local workflows and worker restart/pause checks |
| Real sales HTTP integration | Passed: two separate worker processes, mock correspondence, proposal/quote/acceptance; no invoice, payment or publication |
| Real browser workflow | Passed in Chromium: owner setup through accepted Phase 5 brief, worker-generated site, QA review, preview, revision and approval |
| Browser errors | Zero JavaScript page exceptions; zero HTTP 5xx responses |
| Browser external requests | `fonts.googleapis.com` was intercepted and blocked; no external website, email or payment provider was contacted |
| Dependency/whitespace checks | `pip check` reported no broken requirements; `git diff --check` passed |

Browser screenshots and structured results are in `validation/evidence/phase6/`: `website-desktop.png`, `website-mobile.png`, `browser-results.json`, and the Phase 5 regression screenshots. The preview screenshots are synthetic and not customer work.

## Verified behavior and boundaries

- The local renderer produces separate static documents for multi-page briefs; generated values are escaped and arbitrary generated code is not executed.
- Preview responses carry a restrictive CSP sandbox and are shown in a sandboxed iframe. Form destinations and external resources are blocked. Native required/email fields are validated, but the preview form does not send or store submissions.
- Version approval requires a passed QA report and owner confirmation. Restoring an older version creates a new review version. Publication is never enabled by this phase.
- Optional AI-assisted copy is routed through the Phase 5 one-use request approval and spending ceiling; tests mocked its result. No paid model request was made. The AI may provide bounded text only; AgencyOS builds pages locally.
- QA covers navigation targets, form fields/labels, page metadata/landmarks, missing accepted services, unsafe markup, missing image alt text and common unsupported-claim phrases. This is an automated basic check, not a legal or exhaustive accessibility certification.
- Testimonials, addresses, credentials, actual client logos and contact destinations are omitted unless supplied through a future explicit approved input. Hosting, deployment, custom domains and live contact delivery remain later work.

## Commands

```sh
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python tests/smoke_server.py
.venv/bin/python tests/smoke_sales.py
.venv/bin/python tests/browser_phase5.py --artifacts validation/evidence/phase6
.venv/bin/python -m pip check
git diff --check
```


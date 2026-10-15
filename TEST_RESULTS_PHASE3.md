# Phase 3 validation

Validation used Python **3.13.5**, Flask **3.1.3** and SQLite **3.46.1** on Linux. This establishes Python 3.13 execution, not a claim that the developer operated a MacBook or tested a browser visually. The cloud interpreter lacked ensurepip; its isolated environment was prepared with uv using the declared Flask requirement. The macOS README uses the Python.org distribution's normal venv/pip workflow.

## Automated checks

- `python -m unittest discover -s tests -v`: **73 tests passed**.
- `python tests/smoke_server.py`: **passed**, with a real Flask process, authenticated HTTP requests and a separate real worker process.
- Dependency consistency and Git whitespace checks passed.

The unit/integration suite retains coverage of login/logout, CSRF, dashboard, manual/CSV leads, duplicate review, quotes/invoice amounts and statuses, projects, template/AI draft errors, Phase 2B agent states/approvals and preserved task history.

New coverage includes:

- Disabled/missing/expired OSM policy records and explicit operator attestation; review files cannot be overwritten.
- Search input validation, Overpass query construction, real provider JSON mapping, contact fields left blank when missing/invalid, caching, limits, HTTP failures/backoff and incomplete results.
- Candidate approval/rejection, source timestamps/URLs, duplicate rechecking and prevention of repeated imports.
- Selected source evidence, owner-supplied versus inspected evidence labels, immutable snapshots, approval of inspected observations, and rejection of invented AI evidence references.
- Explicit AI consent, configuration-change reapproval, one request per job, daily limits and no fake output after failure.
- Local and mocked-AI research, approved research required for drafting, saved draft versions/reviews and manual follow-up dates. Quick AI drafts also require cost approval.
- Queue ownership, overlapping claims, deferred readiness, cancellation, interrupted leases without automatic requeue, disabled agents and pending/input limits.
- HTTPS/robots opt-in, private-IP rejection, proxy refusal, redirect blocking, public-IP/TLS-host pin selection, content extraction and provenance.
- Authentication/ownership checks, CSRF and escaping of untrusted evidence.
- Additive upgrades from a synthetic Phase 2B database, unchanged saved legacy task content and an untouched original synthetic backup, plus repeatable migrations.

The HTTP smoke test additionally exercises original agent result review and separate action rejection, Phase 3 local research through the worker, approved-research drafting, and saved draft review/history.

## Deliberately not claimed

- **No live OSM discovery:** official policy/documentation hosts returned proxy HTTP 403. Live discovery remains disabled until a real operator review confirms current permitted use and setup. Mocked records are test fixtures, not live search results.
- **No paid AI calls:** external models were mocked, including failures. Real account access, pricing and model compatibility require operator setup and an approved live check.
- **No real customer records:** all records were fictional and all development/tests used temporary separate databases. An original customer database was not supplied.
- **No live website inspection:** external fetches were mocked. The disabled-by-default fetcher needs explicit permitted-use confirmation and a supported direct network.
- **No emails/payments/publication or public deployment.** Action approvals and reminders do not execute those actions.
- **No browser visual test, complete security audit, autonomous revenue validation or active recurring scheduler.**

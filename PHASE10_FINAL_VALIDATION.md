# Phase 10 final validation

Date: 2026-10-16 (Australia/Sydney)

## Implemented

- Private local staging of only the current owner-approved, QA-passed static website version. Files have a SHA-256 manifest and size/path/script checks; writes are atomic and a prior artifact is never overwritten.
- Explicit public deployment interface with a fail-closed unavailable adapter. No hosting credentials, remote provider, server process, DNS or publication action is configured.
- Owner-visible integrity checks. Missing, changed or invalid artifacts create an attention alert; checks never repair files.
- Audited local staging history and rollback pointer. A prior release must have a passing recorded check before an owner can select it as current.
- `manage.py maintain --phase10 [--watch]` checks current local releases and records exceptions, at most once per UTC date per release. It performs no repair or deployment.
- Production preparation guidance for DNS, TLS, external secrets, backups/restores, monitoring, access and retention is in `PHASE10.md`.

## Validation results

- `.venv/bin/python -m unittest discover -s tests -p 'test_phase10.py'`: **4 passed**.
- `.venv/bin/python -m unittest discover -s tests`: **211 passed**, 0 failures.
- `.venv/bin/python tests/smoke_server.py`: pass.
- `.venv/bin/python tests/smoke_sales.py`: pass; synthetic sales/payment and existing worker gates remained intact.
- `.venv/bin/python tests/browser_phase5.py --artifacts output/pdf`: pass in Chromium; prior website generation/review and Operations flows remained functional.
- `git diff --check`: pass.

## Limits

Staging is a local folder, not an isolated cloud or network staging service. No public deployment, live domain, TLS endpoint, production backup or external availability check was created or verified. The maintenance checker reports file-integrity issues only and does not claim the customer's public site is healthy.

# Phase 9 final validation

Date: 2026-10-16 (Australia/Sydney)

## Implemented and audited

- Licensed-source CSV intake preserves source identity, URL, observation time, licence, permitted-use notes, attribution, owner reviewer and expiry. Expired records cannot be imported into the CRM.
- OSM discovery is a fixed, bounded adapter with required attribution, rate/daily limits, cached requests, and a fail-closed current policy attestation. It remains disabled by default.
- Candidate duplicate flags and deterministic qualification reasons are shown before owner-controlled import. Duplicate import requires explicit review acknowledgement.
- Sales stores owner-attested contact eligibility evidence by normalized email, including basis type, evidence reference, review timestamp and optional expiry. The form says the record is not independently verified and does not authorize sending.
- Existing email safeguards remain: no live transport, mock dispatch limited to fictional workflows and reserved domains, exact expiring message approval, normalized suppression, opt-out/bounce/complaint stops, signed/idempotent event records, and no automatic resend after uncertain outcome.

## Validation results

- `.venv/bin/python -m unittest discover -s tests -p 'test_phase9.py'`: **3 passed**.
- `.venv/bin/python -m unittest discover -s tests`: **207 passed**, 0 failures (48.132 seconds).
- `.venv/bin/python tests/smoke_server.py`: pass; Phase 3/4, Agent Center, Operations and all workspace routes responded successfully.
- `.venv/bin/python tests/smoke_sales.py`: pass; concurrent sales workers, mock-only dispatch, signed reply/event handling, follow-up stop, quote and owner-attested acceptance flow passed.
- `.venv/bin/python tests/browser_phase5.py --artifacts output/pdf`: pass in Chromium; login, navigation, discovery, sales research/outreach review, fictional mock dispatch, proposal/quote, Phase 6 website workflow, Operations and pause/resume passed.
- Browser networking remained intercepted outside the local app; no live source, email, AI, payment or publishing service was contacted.
- `git diff --check`: pass.

## Limits

Owner-attested eligibility evidence is not a legal determination or independent verification. No live email adapter or live discovery activation is enabled by default. Source terms, lawful basis, privacy, provider permissions and sender authentication must be verified separately before any future production integration.

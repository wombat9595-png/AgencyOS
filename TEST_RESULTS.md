# Phase 4 milestones 1–3 validation

Validated on Linux with **Python 3.13.5**, **Flask 3.1.3** and **SQLite 3.46.1**. This establishes actual Python 3.13 execution, not MacBook or visual-browser validation. The cloud Python 3.13 environment was created outside the repository with uv; the MacBook README uses the normal Python.org venv/pip workflow.

## Final checks

- `python -m unittest discover -s tests -v`: **106 tests passed**, no failures, skips or expected failures reported (30.108 seconds in the final run).
- `python tests/smoke_server.py`: **passed** using real local HTTP, authenticated forms and separately restarted worker processes.
- `uv pip check --python /workspace/.agencyos/venv313/bin/python`: all seven installed dependency packages compatible.
- `git diff --check`: passed.

The previous 73 tests remain, including preservation/migration coverage for legacy records and tasks. One existing assertion was updated intentionally: the default database is now `.development/agencyos-phase4.db`, separate from Phase 3.

## New automated coverage (33 tests)

- Authentication, CSRF, ownership and escaped untrusted source content.
- Immutable qualification snapshots, real deterministic output, atomic research handoff, review replay prevention and zero-cost ledger entries.
- Emergency pause across new/legacy queue claims and mutation endpoints; audit callback pause before a subsequent dispatch.
- Atomic budget reservation, changed-reservation rejection, unknown/negative costs and conservative unresolved reservations.
- Concurrent worker claims, expired leases, bounded local recovery and refusal to auto-retry external audits.
- Persistent local schedules, disabled schedules, missed-slot handling and worker execution independent of a browser session.
- Australian offline location schedules, state/city/industry filtering, source expiry and cross-batch provider/ID deduplication.
- Licensed candidate staging/import, evidence timestamps, provenance, blank contact fields, qualification reasons, expired permission refusal and all-or-nothing validation.
- Duplicate checks across separate datasets and existing CRM leads; no silent merge/overwrite.
- Audit permission/configuration gate, expiry/input-change reapproval, disabled-agent refusal and no fabricated failed output.
- Owner review required before audit evidence becomes available to existing research; changed website invalidates audit-based qualification points.
- Actual static HTML extraction against mocked transport responses; verified scoped 404s, metadata/viewport findings, hashes, contact links and separate recommendations.
- Robots restrictions per path, slower crawl refusal, bounded same-origin traversal and exclusion of queries/downloads/external links.
- Redirect/error uncertainty, base URL handling, malformed URLs, valueless HTML attributes and compressed-body refusal before metadata analysis.
- Repeatable migrations and preservation of owner audit-agent enable/disable choice.

Existing transport tests additionally cover private/reserved DNS rejection, TLS hostname/IP pinning and proxy refusal. External providers and network results are mocked; fixtures are not real business discoveries.

## Real-process smoke coverage

The smoke runner starts the actual Flask app with a temporary synthetic database. It exercises owner setup/login, the existing dashboard/pages/styles and earlier task flows. For Phase 4 it assigns qualification through HTTP, starts a separate worker, checks the local research handoff, enables a persistent local schedule, restarts workers, pauses before a claim and resumes work. All smoke processes stop and their temporary databases are removed.

## Not claimed

- No real business data, live discovery, paid AI call, live website audit, email, invoice issue, charge, publication or public deployment was performed.
- No current nationwide provider licence was independently verified; official policy pages were blocked by the outbound proxy during planning. Offline imports require owner-reviewed permission records. Public OSM automation remains separately gated, not promoted to nationwide scraping.
- The current website transport refuses outbound proxy use. Live audits need permission, explicit task approval and a supported safe direct network. Mocked success does not prove live connectivity.
- No always-on daemon, cloud hosting, production security/legal certification, complete accessibility/performance audit or autonomous revenue validation is included.
- The new zero-dollar ledger applies to Phase 4 tasks, not preserved legacy paid-AI routes. No positive-cost Phase 4 executor is installed.
- Original customer databases were not selected or modified. Migration tests use synthetic originals/copies.

Original Phase 3 results are retained in [TEST_RESULTS_PHASE3.md](TEST_RESULTS_PHASE3.md). Operational details and remaining work are documented in [PHASE4.md](PHASE4.md).

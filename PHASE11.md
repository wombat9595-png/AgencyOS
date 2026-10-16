# Phase 11 — Integration, security and final readiness

Phase 11 connects the existing synthetic workflows across Phases 5–10 and records what is usable locally versus what remains unconfigured. A representative fictional lifecycle is covered in `tests/test_phase11.py`: owner-reviewed contact evidence, accepted quote, approved and locally staged static site, passing artifact check, signed mock payment webhook, and a daily Operations summary carrying invoice/payment provenance and local release state.

## Installation and local operation

- Python virtual environment with the packages listed in `requirements.txt` (Flask, ReportLab and cryptography); SQLite is the local data store.
- Start the Flask application on its default loopback address with `python app.py`. Use the same `AGENCYOS_DB` path for the app and workers.
- Use the phase-specific local worker commands documented in `PHASE4.md`, `PHASE5.md`, and `PHASE8.md`. Use `python manage.py maintain --phase10` for local staged-artifact checks.
- Back up the SQLite database before upgrades or migrations. Use a copy to validate upgrades and restoration.

## Integration and security review

- Authentication, owner-scoped records, CSRF tokens, bounded request sizes, safe static-site rendering, owner review gates, signed/idempotent mock events, approval expiry and emergency pause are covered by the test suite and existing phase reports.
- The app binds to `127.0.0.1` by default. It is a local single-host application backed by SQLite, not a hardened public service.
- Without `AGENCYOS_SECRET_KEY`, the app creates a fresh random session key at startup; sessions will not survive restarts. Configure a private stable secret before multi-process local use. The cookie is HTTP-only and SameSite Lax; secure-cookie/TLS settings and deployment proxy configuration need production-specific work.
- Login rate limiting, multi-user roles, operational monitoring, tested automated backups, retention/deletion policy, independent penetration testing and external hosting security are not certified by this milestone.
- Contact-basis records and source licences are owner-attested; neither the software nor tests independently verify legal permission.

## Readiness inventory

| Area | State |
|---|---|
| Local application, SQLite, workers, schedules, static generation and previews | Implemented; local use |
| Source discovery | Licensed-data import and bounded OSM code available; OSM disabled until operator review |
| AI | Optional adapters gated by request approval and budgets; defaults are zero/off |
| Email | Mock-only; no live transport |
| Payments | Local signed mock and isolated Stripe test-mode path; no production payment flow |
| Website staging | Private local static artifacts with checks/rollback |
| Public hosting, DNS, TLS, external monitoring | Not configured; no public deploy adapter |
| Production backups, retention and disaster recovery | Guidance only; not configured or restore-certified |

Local deterministic work has no provider-call charge; it uses the operator's computer and storage. Optional AI, data, hosting, domains, transaction processing and operational services are not activated or priced in this project. Check each provider's current terms, region and prices before separately configuring one.

No live email, external discovery request, AI request, charge, public publication, domain change or deployment was performed for this milestone.

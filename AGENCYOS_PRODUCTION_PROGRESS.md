# AgencyOS production preparation progress

Branch: `codex/agencyos-production-prep`. Starting remote checkpoint: `8df0f2f`. Date: 2026-10-16 Australia/Sydney.

## Current milestone

M1 audit and independently verified baseline complete; M2 security/infrastructure in progress.

## Milestones

- [x] M1: inspected source, phase reports, schemas, queues and integration boundaries; compared source tree with remote checkpoint; independently ran Python 3.13.16 baseline: 212 tests passed (50.204s). See `PRODUCTION_READINESS_AUDIT.md`.
- [ ] M2: confirmed vulnerability fixes, strict production configuration, WSGI/supervision, encrypted backup/restore, health/alerts and migration tooling.
- [ ] M3: verified official provider research, Canberra discovery controls, email sandbox and DNS/eligibility/unsubscribe preparation, website delivery and payment hardening.
- [ ] M4: owner launch dashboard, accelerated operations workload, complete synthetic lifecycle, security/browser evidence, final readiness report and pushed branch.

## Bugs and security concerns

Initial audit: login throttling absent; installation-wide records require single-owner enforcement; public mock payment secret; incomplete payment provenance/deduplication; stale local tasks; static release navigation/integrity/rollback gaps. Fixes and executed tests will be added at each milestone.

## External dependencies and spending

No services purchased or paid APIs activated. Provider accounts, business identity/ABN/GST, lawful outreach evidence, verified sender domain, hosting/domain selection and live financial/publication approvals remain external prerequisites. Independent preparation proceeds with synthetic databases and mocked provider transports.

## Next actions

Complete M2, then M3/M4. Preserve earlier branches and customer data. No live communications, invoices, payments, domain mutation or public deployment is authorized.

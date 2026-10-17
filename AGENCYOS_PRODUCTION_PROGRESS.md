# AgencyOS production preparation progress

Branch: `codex/agencyos-production-prep`. Starting remote checkpoint: `8df0f2f`. Date: 2026-10-16 Australia/Sydney.

## Current milestone

M1–M4 local preparation complete; final report and validation evidence prepared for branch delivery. Live launch remains blocked by the prerequisites in AGENCYOS_PRODUCTION_READINESS.md.

## Milestones

- [x] M1: inspected source, phase reports, schemas, queues and integration boundaries; compared source tree with remote checkpoint; independently ran Python 3.13.16 baseline: 212 tests passed (50.204s). See `PRODUCTION_READINESS_AUDIT.md`.
- [x] M2: strict production session/host/bootstrap configuration, single-owner boundary, durable login throttles, audit metadata; public mock-secret removal and Stripe payment provenance fixes; active-markup/release navigation/rollback checks; stale local worker recovery; Gunicorn/systemd/nginx preparation; encrypted online backup/isolated restore and alerts. **224 tests passed (54.283s)**; actual Gunicorn provisioning/login/health/host/backup/restore smoke passed. Dependency audit found seven advisories in cryptography 46.0.7; upgraded to 50.0.2 and reran audit: no known vulnerabilities. `pip check` passed.
- [x] M3: verified official provider research, Canberra discovery controls, email sandbox and DNS/eligibility/unsubscribe preparation, website delivery and payment hardening. Focused production suite: 20 tests passed; expanded review-only AI research/QA workflow tests passed (2 tests, mocked HTTP only).
- [x] M4: owner launch dashboard, accelerated operations workload, complete synthetic lifecycle, security/browser evidence, final readiness report and branch delivery. Final Python 3.13.16 suite: **235 tests passed in 58.520s**. All Flask/sales/Gunicorn/overnight/Chromium checks passed; no known dependency advisories and no broken requirements. Production lock installed and Gunicorn smoke passed in a fresh temporary venv. Linux daemons/public TLS/provider accounts remain untested.

## Bugs and security concerns

Confirmed initial gaps above were addressed in M2. A strict-host rejection initially triggered the HTML error renderer without a valid URL adapter; fixed to return a plain 400. Cross-owner requests now uniformly reject unknown/secondary-owner sessions; two legacy assertions were updated to require the stronger boundary. Current limitations: Linux service runtime, public TLS, off-host backup destination and external notification delivery are not configured/tested.

## External dependencies and spending

No services purchased or paid APIs activated. Provider accounts, business identity/ABN/GST, lawful outreach evidence, verified sender domain, hosting/domain selection and live financial/publication approvals remain external prerequisites. Independent preparation proceeds with synthetic databases and mocked provider transports.

## Next actions

Resolve the concrete provider/business/hosting decisions listed in the final readiness report before live launch. Provider accounts and public deployment remain outside this completed local preparation run. Preserve earlier branches and customer data. No live communications, invoices, payments, domain mutation or public deployment is authorized.

## Final discoveries and fixes

Public opt-out originally conflicted with the global pause/session gates; those routes now stay available. Review-only research assistance now resolves ownership from its flow when estimating approvals. Payment review added canonical transaction requirements, monotonic receipt-bounded mock refund updates, mixed-object review holds and an explicit invoice confirmation gate. These changes passed the final complete suite. Final Chromium evidence includes the Launch dashboard at 1440px and 390px, with no horizontal page overflow or JavaScript/server errors. Overnight simulation completed 21 local tasks using two real workers, recovered one expired task, deduplicated schedule/summary and left paid work untouched. No live communications, money movement, customer-domain changes or public deployment occurred.

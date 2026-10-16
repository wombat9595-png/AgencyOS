# AgencyOS master implementation roadmap

Updated: 2026-10-16 (Australia/Sydney). Statuses reflect this checkout, not intended functionality.

## Dependency map

```text
Phase 5 accepted quote + owner-attested project brief
  └─ Phase 6 versioned static website builder + isolated preview + QA
      ├─ Phase 7 invoice drafts + payment-provider sandbox/reconciliation
      ├─ Phase 8 durable agent orchestration + schedules + operational dashboard
      ├─ Phase 9 authorized discovery + outreach provider boundary
      └─ Phase 10 isolated staging/deploy adapters + monitoring/rollback
           └─ Phase 11 lifecycle acceptance, security review and readiness report
```

Phase 7 and parts of Phase 8–10 may be developed from the Phase 5 interfaces in parallel at the implementation level, but end-to-end lifecycle acceptance depends on stable Phase 6 and shared operational controls. External provider activation is never implied by development completion.

## Milestone acceptance criteria

| Phase | Dependencies | Acceptance criteria | Status |
|---|---|---|---|
| 6 — Website builder, preview, revisions, QA | Phase 5 accepted brief and project linkage | Local no-paid-AI generation; accepted scope/branding and supplied facts only; safe static output; responsive one/multi-page layouts and themes; owner-scoped version history; isolated desktop/mobile preview; review/revision/restore/approve flow; QA for links/forms/pages/images/accessibility/SEO/unsafe claims/scope with critical blockers; synthetic multi-industry browser demonstration and screenshots. | **Complete — passed 186-test suite, HTTP/worker smoke tests and real Chromium flow.** |
| 7 — Invoices and payments | Phase 5 quote/acceptance; Phase 6 project readiness where applicable | AUD invoice drafts and numbering, itemization/GST/terms/dates/PDF, secure owner-configured bank details with no fictional production defaults; provider abstraction; sandbox hosted links/webhook signature verification/idempotency/reconciliation/partial-payment/refund/dispute state; only evidence-backed or owner-reconciled paid state; full synthetic workflow. | **Complete — 195 tests; HTTP/worker/Chromium checks; reviewed synthetic invoice PDF.** |
| 8 — Multi-agent operations | Durable job/store patterns from Phases 3–7 | Named agents with actual handlers; durable internal handoffs, independent concurrency, retries/recovery/cancel, recurring local-time scheduling, emergency pause, rate/cost ceilings, health/failure/exception dashboard and daily summaries; restart/concurrency tests. | **Complete — 204 tests, HTTP/sales smoke checks and Chromium workflow passed.** |
| 9 — Discovery and compliant outreach | Phase 8 queues and provider controls | Licensed/authorized-source adapter interface, source attribution/use-policy metadata, deduplication and explainable scoring; synthetic fixtures; email adapter boundary with credentials kept outside DB/logs, eligibility/consent evidence, suppression/unsubscribe/bounce/complaint safeguards; local/sandbox-only until provider permission and legal configuration verified. | **Complete — 207 tests; source and email safeguards reviewed; owner-attested contact evidence added.** |
| 10 — Hosting, publication, maintenance, production preparation | Phase 6 artifacts; Phase 8 scheduling | Isolated staging/deploy adapters, domain/DNS guidance, TLS/backup/rollback/health checks; maintenance checks create tasks/alerts without claiming repairs; local or sandbox deployment verification; production architecture, backups/restore, secret handling, auth/rate limits, monitoring, retention and disaster recovery documentation. No public deployment or live-domain change. | **Complete — local static staging, integrity alerts and audited rollback; 211 tests and smoke/browser regression passed.** |
| 11 — Integration, security and final readiness | Phases 6–10 | Synthetic lifecycle from authorized fictional lead through verified sandbox payment and operations summary; broad unit/integration/server/worker/browser/accessibility/security/gate regression suite; screenshots/invoice/sandbox evidence; documented installed/configured/mock-only/missing status, operating requirements/cost ranges, limitations and installation/deployment instructions. | **In progress** |

## Cross-phase engineering rules

- Keep changes additive and preserve the Phase 3–5 queues, records, migrations and gates.
- Use synthetic records and temporary databases for development. Preserve customer database files; migrations are tested on copies.
- Represent simulated, pending, owner-recorded, provider-verified and live outcomes as distinct states.
- Never execute generated website code in the AgencyOS process; generate bounded static files and preview them on an isolated local origin.
- Do not infer permission to contact, acceptance, revenue, invoice payment or publication authorization from nearby workflow state.
- Mock and sandbox adapters are the default; no purchase, live charge, real email, public deploy or live domain mutation in this program.
- Record each milestone's commands, pass/fail counts, browser details, screenshots/logs, fixes and commit in `AGENCYOS_MASTER_PROGRESS.md`.


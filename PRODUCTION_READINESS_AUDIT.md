# AgencyOS production readiness audit

Audited 2026-10-16 against remote checkpoint `8df0f2fbe8bd14f567fc34ab424dce028cc77df8`, tree `5db13d190264c5bdf20324848ee7c326d137fd3e`. Local commit differs because prior milestones were published using the GitHub Git Data API; the source trees match exactly. Python 3.13.16 baseline: **212 tests passed in 50.204 seconds**. Source, additive schemas, phase reports, worker queues and provider gates were inspected. This document records the initial audit; fixes and final evidence are tracked in the production progress/report.

| Capability | Actual implementation | Initial readiness |
|---|---|---|
| Discovery | Owner-attested licensed CSV and bounded OSM adapter; attribution, expiry, duplicate review | IMPLEMENTED AND TESTED locally; REQUIRES CONFIGURATION and source permission for external data |
| Qualification/research | Deterministic evidence rules; optional AI synthesis | IMPLEMENTED AND TESTED locally; optional AI REQUIRES OWNER APPROVAL |
| Website audit | Bounded public HTTPS/static-page transport, robots, DNS pinning; fixtures tested | REQUIRES CONFIGURATION and exact-origin permission; proxy transport unsupported |
| Outreach/replies/proposals | Local text/rules and optional bounded AI; human review | IMPLEMENTED AND TESTED locally |
| Email | Mock acceptance/events only; real provider interface has no transport | SANDBOX ONLY; live sending NOT IMPLEMENTED |
| Quotes/acceptance | Integer AUD/GST calculations, immutable versions, owner-attested acceptance | Local preparation works; customer identity/acceptance not independently verified |
| Website build/QA | Fixed escaped static templates, optional AI text, isolated previews, local release folder | Local pilot preparation; production contact form/publication NOT IMPLEMENTED |
| Invoices/payments | Synthetic PDF approval, local signed mock, Stripe test adapter with mocked network | SANDBOX ONLY; actual Stripe account integration untested |
| Operations | Durable Phase 3/4/5 queues and local Phase 8 scheduling/summary; manual processes | Local handlers work; supervised 24/7 operations NOT PRODUCTION READY |
| Project Manager agent | Catalogue entry without execution handler | NOT IMPLEMENTED |

## Confirmed gaps requiring fixes

- No login throttling; deployment configuration does not enforce stable secrets, secure cookies or session expiry. Core leads/manual records are shared installation records, not tenant isolated. The supported boundary must be one owner per installation.
- `/setup` and `/login` run migrations during requests. Production needs explicit migration/startup procedures and a WSGI server.
- Mock payment webhook falls back to a public default secret. Payment event deduplication does not reject changed-content replay; Stripe checkout completion needs paid-state/test-mode and canonical transaction checks before it can represent payment.
- Phase 8 worker can leave local tasks Running indefinitely after a crash. No process supervisor, encrypted backup or verified restore exists.
- Local staging checks scripts but does not fully validate active HTML or recheck source QA; static multi-page navigation still uses preview query links. Rollback trusts an old check rather than rechecking files at execution.
- Contact-basis evidence is stored but not an email-send authorization. Sender DNS/provider verification, public unsubscribe, inbox integration and actual email transport remain unfinished.
- Dashboard mostly mixes legacy workflow counts with newer modules; accurate live/test provenance and unknown operating costs need explicit presentation.

## Commercial boundary

READY FOR LOCAL USE for internal drafting, review, fictional workflows and private website generation. A controlled real-data internal pilot requires source permission, privacy/retention decisions, verified business configuration and secure hosting/backup controls. No evidence supports unattended real customer outreach, payment collection or publication. Development tests are not penetration testing, legal certification or a production reliability guarantee.

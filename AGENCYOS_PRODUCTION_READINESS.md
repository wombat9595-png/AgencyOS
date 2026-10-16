# AgencyOS production launch preparation

Assessment date: 2026-10-16. Branch: `codex/agencyos-production-prep`. Starting remote checkpoint: `8df0f2f`. **The system is ready for local preparation and synthetic operation. It is not ready for autonomous commercial production.** No provider account, sender domain, live financial configuration or public deployment was activated.

## Readiness decisions

| Category | Capabilities / limits |
|---|---|
| READY FOR LOCAL USE | Single-owner authenticated CRM, approved licensed fixture intake, deterministic qualification/research, bounded permitted audit fixtures, outreach/proposal drafts, exact AUD/GST quotes, owner-attested acceptance, static website builds/revisions/QA, isolated previews, private staging, handover ZIP, integrity monitoring/rollback, synthetic invoice PDFs, signed mock payments and reconciliation, local operations dashboard. |
| READY FOR CONTROLLED PILOT | Fictional internal agency workflow and supervised saved-record automation. Use of real data remains conditional on source permission, privacy decisions and destination-host hardening. This category does not authorize real customer communications, financial actions or public sites. |
| REQUIRES EXTERNAL CONFIGURATION | Approved Sydney host, TLS/domain, private secrets, verified business identity/ABN/GST, authorised data supplier, actual sender DNS/SES identity, off-host backup destination, external monitoring recipient, and account-level sandbox credentials. |
| BLOCKED | Live email/financial/publication activation lacks explicit owner approval and verified provider/customer prerequisites. No paid service was purchased. |
| NOT IMPLEMENTED | Live email dispatcher and actual inbox/SNS ingest, public hosting/DNS/certificate executor, production contact forms, real invoice issuance/delivery, live Stripe collection and settlement reconciliation, bank feed, subscriptions/verified MRR, executing Project Manager agent, multi-tenant access, MFA and managed PostgreSQL. |

## What actually works

The Agency Manager coordinates durable local queues with explicit review handoffs. Lead research and qualification use saved evidence/rules. Outreach, reply interpretation and proposal agents have local handlers and optional approved AI. Website generation/revisions use escaped static templates and optional AI text; deterministic QA retains authority. AI research synthesis and QA assistance are review-only. Project Manager remains a planned catalogue entry. No catalogue label implies a running independent AI service.

The new `/launch` dashboard shows agent availability, recent worker phases, research/qualification, prepared correspondence, reply provenance, quotes, accepted briefs, built/approved sites, staging, synthetic invoices/payments, open alerts, pending reviews and owner-recorded expenses. Live receipts exclude synthetic, legacy/manual statuses. AI reservations are visibly separate from actual bills; hosting/AI expenses need receipts. MRR is explicitly unknown. Zero live send/publication/issuance counts reflect unavailable executors, not measured commercial throughput.

The saved Canberra plan constrains authorised licensed imports by state/city/industry, source score and daily volume. Paid research has an additional reservation ceiling, alongside the shared paid-request gate. No discovery starts when settings are saved. Detailed provider rights, prices and unverified conditions are in `PROVIDER_INTEGRATION_REVIEW.md`.

## Security work and residual risks

| Area | Confirmed changes and evidence | Remaining limit |
|---|---|---|
| Authentication/access | Stable production secret, explicit trusted hosts, secure host cookie, eight-hour session, persistent hashed login-attempt limits, sole-owner installation boundary, production web setup blocked. | Shared legacy records are not tenant isolated. MFA/recovery and account lifecycle need design. Protect access behind a private network or approved access gateway for a pilot. |
| Request/browser safety | Existing CSRF/escaping/SSRF and isolation controls retained; production security headers, HSTS, no-store and metadata-only logs. Unsubscribe and signed evidence intake remain available during pause/invalid sessions. | CSP still allows inline code for legacy UI. Refactor to nonce/external assets before a broader exposure; no independent penetration test performed. |
| Generated websites | Active HTML/resource checks, deterministic QA rerun at staging, static link export, bounded file/hash/symlink checks and immediate rollback integrity validation. | Fixed templates are not a complete professional accessibility/content/legal review. Public contact forms, customer origin and public monitor are unavailable. |
| Financial evidence | Removed public default webhook key; reject changed-content replay, live/unpaid Stripe test events and missing canonical transaction; dedup checkout/payment-intent credits. Invoice test approval requires confirmation. Bank values encrypted and blanks preserve existing ciphertext. | Stripe account tests not run. Stripe refund events are held for correlation review. Mock cumulative refund updates are monotonic, capped by receipts and cannot mix object types. Actual settlement, dispute resolution and live ledger certification remain unimplemented. |
| Recovery/secrets | Explicit migration copies, private key-file support, encrypted SQLite online backups with artifact manifests, isolated no-overwrite restore/integrity tests, bounded local task recovery tokens. | Bank/backup key escrow/rotation and off-host recovery must be configured. Local backup ceiling 128 MiB; single-host SQLite has no HA. |
| Dependency review | Cryptography upgraded from vulnerable 46.0.7 to 50.0.2. Current pinned production dependencies and pip audit evidence retained. | A clean advisory scan is date-bounded and does not prove absence of vulnerabilities. Linux install/runtime must be rehearsed. |
| Privacy | Source permission/expiry and consent references, suppression, no automatic personal-data deletion, bounded inputs and redacted operational logs. | Owner must define purpose/retention, access requests, deletion/backup expiry policy, vendor residency and privacy notices. No legal certification or automatic retention purge. |

## Infrastructure and operations

`DEPLOYMENT.md`, `wsgi.py`, `production.py`, `requirements-production.lock` and `deploy/` contain the prepared configuration. Gunicorn runs on loopback behind a planned TLS reverse proxy; separate Phase 4/5/8 services and backup/check timers are supplied. SQLite is limited to a single host/owner pilot; PostgreSQL requires an application migration before multiple hosts/tenants. Existing data and earlier branches are preserved.

Failed/interrupted jobs, queued work without a matching heartbeat, high AI reservations and stale/missing backups create deduplicated dashboard alerts. Service failure templates write to the system journal. **External paging/email notifications are not configured**, and a host outage cannot alert through its own dashboard. Daily summaries are local records. Proposed RPO 24 hours/RTO 2 hours are engineering targets, not measured cloud recovery guarantees.

## Validation evidence

The independent baseline passed 212 tests. **Final suite: 235 tests passed in 58.520 seconds on Python 3.13.16, macOS ARM64.** All eight execution checks and service/source static checks passed; the dependency audit reported no known vulnerabilities. A separate clean temporary environment installed the production lock, passed dependency checks and ran the strict Gunicorn smoke successfully. Final results, commands, runtime and host details are recorded in `validation/evidence/production-final/validation-results.json` and individual logs. The suite includes Python 3.13 tests, current migrations, owner boundaries/CSRF/SSRF/XSS guards, budget/pause/lease/concurrency controls, provider fixture contracts, synthetic payments, websites and backup/restore. `tests/validate_production.py` reproduces the local run.

- Full synthetic Canberra acceptance test: authorised fixture CSV → qualification → research → permitted robots/HTML audit fixtures → reviewed outreach → mock dispatch → fictional reply → reviewed reply-agent handoff → proposal → exact quote → fictional acceptance → project brief → website build/QA/approval → private staging/check → synthetic invoice → signed mock payment → reconciliation/daily operations → deployment preparation/private handover → local rollback → encrypted artifact/database restore. It also tests mocked AI QA suggestions cannot alter approved version/QA. No provider network call is used.
- Actual localhost Flask HTTP and separate concurrent sales worker processes, plus actual Gunicorn with strict configuration, secure cookie/host rejection, explicit provisioning, encrypted backup/restore and migration copy/source preservation.
- Accelerated overnight workload: two concurrent processes complete 21 local tasks, recover one expired local task, produce one scheduled occurrence and one daily summary, then terminate/restart. Pause prevents execution; paid approval tasks remain untouched. This short simulation is not proof of months of reliability.
- Actual Chromium forms and watch workers on macOS ARM64: sales/quote/website revision/approval workflow, isolated desktop/mobile website previews, pause/resume, owner navigation and Launch plan forms at 1440px/390px. Launch has no page horizontal overflow, JavaScript errors or HTTP 500s. Screenshots and browser JSON are retained. Safari was not tested.
- Python source and service-file structure checks. Linux systemd/nginx daemons, public HTTPS, actual AWS/Stripe accounts, real DNS/email delivery and off-host restore were not tested.

## Costs and spending boundary

No new services were bought and no paid API execution was made. AWS public Linux IPv4 list plans reviewed include US$12/month for 2 GB and US$24/month for 4 GB; Sydney has reduced advertised transfer allowance. A US$30–60/month pilot infrastructure allowance is an estimate excluding domains, tax/FX, data, AI, payment fees and support. See the linked official sources in `DEPLOYMENT.md` and `PROVIDER_INTEGRATION_REVIEW.md` for SES, Stripe and model pricing. All actual account quotes and budgets require review before purchase; there is no fabricated revenue or expense estimate presented as an actual receipt.

## Before the first real customer

1. Confirm the legal business identity, ABN/GST treatment, commercial terms and data/privacy policy; provide sensitive bank details privately only when explicitly approving financial setup.
2. Choose/approve hosting and its budget, domain/access model and backup/notification destinations. Run a Linux deployment/TLS/firewall and off-host restore rehearsal on approved resources before exposure.
3. Select a data supplier with written CRM/retention rights and recipient consent evidence. Approve the precise email use case with the provider. Connect/test actual sender verification, inbox/event ingestion and the guarded live dispatcher before any customer message.
4. Approve AI provider/model/data handling and AUD ceilings if wanted; validate current request/token contracts with an authorised account. Local operation needs no paid AI.
5. Complete account sandbox payment/settlement/refund/dispute mapping and real invoicing controls before explicit live activation. No invoice is evidence of receipt.
6. Complete the hosting/contact endpoint/DNS/TLS executor and public monitoring; record genuine acceptance and permission for each exact site revision, then obtain separate publication authorization.

The next owner decisions are the business/legal configuration, permitted data source, hosting/domain budget, and which provider sandbox work to authorize. These are external launch prerequisites. Routine local setup, debugging and synthetic testing have been completed by the agent.

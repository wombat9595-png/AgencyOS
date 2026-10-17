# Phase 5 architecture, integration requirements and limitations

## Working sales workflow

Phase 5 adds persistent sales opportunities and named jobs to the existing Flask/SQLite application. It does not replace Phase 3/4 queues or copy their results into fake customer records. New opportunities require an explicitly approved lead and 1–5 owner-priced package versions. They can import owner-approved Phase 3/4 research for the same unchanged lead, or create local research and wait for review.

The implemented path is:

1. Lead approved for internal work → local research or matching approved research snapshot.
2. Research review → queued outreach generation.
3. Draft review → exact correspondence record.
4. Separate recipient/content approval → mock dispatch only.
5. Original reply/event → queued classification; owner review → queued reply draft.
6. Owner-recorded requirements → queued proposal; proposal approval → deterministic quote job.
7. Quote review → correspondence record; exact quote acceptance evidence + explicit owner authorisation → one project brief.

Internal follow-up schedules run eligibility reviews, not sending. They do not manufacture a response or customer interest. Proposal preparation requires actual owner-recorded requirements and their source; a positive reply classification alone does not constitute agreement.

### Functional agents

- **Research:** deterministic organisation of saved facts and selected evidence. It does not claim new external research.
- **Outreach:** actual local drafting with tone, package scope, cited reviewed technical observations, immutable revisions and generation history; optional approved AI writing.
- **Reply and Follow-Up:** conservative local interpretation, original-message preservation, optional approved AI interpretation, reviewed reply drafting, suppression and scheduled internal eligibility reviews.
- **Proposal and Quote:** local/optional AI explanatory proposal writing, exact AUD arithmetic, versioned package/quote snapshots, explicit GST treatment and owner-attested acceptance/project handoff.
- **Agency Manager/worker:** transactional job claims, stage prerequisites, handoffs, independent-opportunity concurrency, schedules, cancellation, recovery, pause and activity history.

These are working handlers, not model-generated tools. Local modes are explicitly labelled rule/template based. AI does not decide financial totals, customer acceptance, permission to contact or payment state. The existing Phase 4 audit remains deterministic actual HTTP checking, separately permission-gated.

## Records, reviews and immutable versions

`sales_store.py` defines additive `p5_*` tables for configuration, package versions, opportunities, jobs, draft versions, messages, events, suppressions, follow-ups, quotes, acceptance evidence, project briefs and AI reservations. Earlier records remain in their existing tables. Inputs and selected evidence are saved with each job; drafts link to their job and supporting evidence. Changing a package does not change an earlier opportunity's selected version.

Research imports require owner-approved jobs, matching lead identity and unchanged name/website. New evidence selection uses the earlier workflow's available evidence gate. Source-reported directory/manual facts remain distinct from owner-reviewed technical observations. Review does not make an external statement independently true. Timestamps and scope remain visible; old research is not represented as a new website visit.

Draft revisions create new records. Pending revisions block approval/dispatch of older drafts. Editing sender settings, recipient/content or provider context invalidates correspondence approval. Quote revisions cannot inherit acceptance. Accepted scope is frozen against normal revision routes; later work needs a separate opportunity/agreement.

## AI authorisation and spending gap closure

The shared `ai_drafts.request_chat` transport now requires a **one-use exact-request capability** issued by `sales_ai.execute` after checks. Legacy direct call sites have no capability, even if API keys are configured or a legacy approval exists. They fail with an explanation directing the owner to approved/budgeted sales jobs. Local legacy workflows and historical results are preserved. There is no environment-variable bypass or permissive development flag.

For optional AI writing/interpretation:

- Reuse `AGENCYOS_AI_PROVIDER=openai-compatible`, `AGENCYOS_AI_ENDPOINT`, `AGENCYOS_AI_MODEL` and `AGENCYOS_AI_API_KEY`, kept outside Git/logs. The endpoint must support the existing HTTPS chat-completions protocol and bounded output parameter.
- Owner configuration must identify the exact model, positive AUD-cent daily/request ceilings and conservative input/output rates in **AUD cents per million tokens**. Convert any foreign-currency prices conservatively and include all supported billing components. Unknown pricing blocks execution.
- Pricing review is an owner attestation, not a live provider verification; it expires after seven days. Do not activate it until actual current terms/pricing are reviewed. Default budget/rates/request count are zero. The UI caps approval settings at AUD 100/day and 100 AI requests/day; lower limits should be used for any future pilot.
- The job page shows its exact inputs and conservative maximum reservation. Approval binds payload, kind, model/provider fingerprint, price rates and output ceiling, expires after one hour, and is rechecked before execution. Changed inputs/model/rates need a new approved request.
- UTF-8 byte counts plus framing allowance conservatively estimate input tokens; output is bounded to 1,000 requested tokens with an additional billing allowance in the cost estimate. Reservations occur under an immediate transaction before calling the provider. The gateway also checks active lease, cancellation and pause.
- Request/money ceilings count **all** reservations for the UTC day. Failed, interrupted and successfully returned requests retain their full ceilings; they are not automatically refunded. Status distinguishes a received response from a provider invoice. Actual provider-bill reconciliation is not implemented.
- Model output must match the writing/classification schema and reference only supplied evidence IDs. Invented IDs/invalid structure fail. Semantic truth cannot be guaranteed by schema checks; every draft/classification needs owner review. AI text cannot override detected opt-outs or create acceptance.

Application reservations are conservative controls, not a guarantee of the provider's final bill. Account-side caps, current model pricing and supported tokenisation/billing behaviour remain prerequisites. No paid or live AI request was performed during development; transport and responses were mocked in tests.

## Email integration boundary

`sales_email.EmailProvider` defines a submission interface with an idempotency key. The installed `MockEmailProvider` returns deterministic `mock:` IDs and **Mock accepted** receipts. It never opens a connection or sends an email. Acceptance is distinct from delivery, reply and real customer contact.

`p5_control` records sender/provider metadata, not credentials. Readiness checks report address configuration separately from SPF/DKIM/DMARC, sender verification, legal/consent review, provider permission and live adapter availability. Those real-world requirements remain **not checked/unverified/not installed**. Selecting `ses-disabled` cannot activate sending. No live adapter or activation switch ships in this release.

Mock dispatch requires an explicitly fictional workflow, a reserved fictional recipient domain, reviewed latest draft/current quote, exact sender/recipient/subject/body approval, unexpired approval and no suppression. It rechecks before execution. At most one attempt per recipient per owner per UTC day and ten attempts per owner/day; an active or uncertain attempt blocks later contact. These are local guardrails, not a claim of provider-compliant real email reputation handling.

An exception/uncertain result is recorded as **Outcome unknown**, not automatically retried. Expired dispatch jobs become Interrupted; records preserve any known receipt. There is no automatic replacement message after uncertain execution. Live activation would require an actual provider adapter, its own idempotency/reconciliation support, legal review, authenticated sender and additional sending tests.

### Events and unsubscribe handling

The authenticated owner can record original correspondence, clearly labelled **owner-recorded; not provider-verified**. It does not change a draft into proof of delivery. Synthetic mock events use `/sales/events/mock` and are labelled mock, never real provider receipts.

For that mock event protocol only:

- Set `AGENCYOS_EMAIL_EVENT_SECRET` securely outside Git/logs (at least 32 characters). It is not needed for local drafting, mock submission or owner-recorded events. Automated smoke tests generate an ephemeral test secret.
- POST raw UTF-8 JSON with `timestamp` (Unix integer), `event_id`, `provider_id` (`mock:` ID), `type`, optional `text`.
- `X-AgencyOS-Signature` is lowercase HMAC-SHA256 hex over the exact raw body using that secret. The timestamp must be within five minutes. Maximum envelope 20 KB, original text 10,000 characters. This is **not** SES/SNS's signature protocol and must not be used as a real SES webhook adapter.
- Supported types: reply, delivered, bounce, complaint, unsubscribe. `(provider,event_id)` is unique. Identical replay returns the existing event; changed content under the same ID is rejected.
- Suppressions normalise address case and are checked at dispatch. Opt-outs, complaints and bounces stop contact. Clear opt-out language is handled before AI interpretation. Other replies immediately stop stale follow-up schedules and require owner attention; delivery events cannot undo suppression.
- Pausing does not block signed event receipt, owner-recorded replies or suppression. Queue pressure cannot roll back original events/opt-outs; deferred classification can be queued later by the owner. There is no agent-driven unsuppression.

No public unsubscribe landing page, RFC one-click unsubscribe headers, inbox polling, real provider webhooks or real SMTP/DNS verification is implemented. Those are mandatory integration work before real sending, not reasons to enable a partially configured sender.

## Quotes, GST, acceptance and Phase 6 interface

Packages support one-page, multi-page, custom and maintenance categories, one-off/monthly billing and quantities. Owners supply prices, inclusions and exclusions; no commercial prices are seeded. Inputs require finite non-negative AUD amounts with at most two decimal places.

GST defaults to **unset**, which blocks quote creation. Explicit choices are not registered (no GST) or registered at 10%, with package amounts excluding GST. Arithmetic uses integer cents and Decimal half-up rounding per line. One-off and monthly totals remain separate. The owner must establish the correct actual tax treatment; quotes are not tax invoices or subscriptions and cannot charge a customer.

Owner-reviewed proposals hand off to deterministic quote jobs. Each quote has an immutable content hash/version. Correspondence uses a human-readable quote summary and excludes internal requirement-source notes. A linked legacy quote stores the one-off draft total/reference, not recurring commitments or acceptance proof. Manual legacy status changes remain possible and are explicitly distinguished from the new acceptance workflow.

Acceptance requires current approved version, matching hash, no pending proposal/quote revision, actual customer identity, acceptance evidence/source, owner attestation and explicit project-creation authorisation. It is **owner-attested customer acceptance, not independent identity verification**. There is no public customer acceptance portal. Agents cannot fabricate these fields or treat a classification as agreement. A unique acceptance/project link prevents duplicate projects.

The stable project brief includes schema version, lead/opportunity IDs, approved requirements/source, branding references, full accepted quote/version/hash, acceptance provenance and project ID. Requirements/branding come from the accepted quote snapshot, not later edited flow fields. Website generation and publication authorisations are explicitly false. No placeholder builder buttons or site generation are included.

## Concurrency, schedules, pause and recovery

`python manage.py worker --phase5 --watch` processes sales tasks and due internal follow-up reviews while the browser is closed. Independent workers can compute for different opportunities concurrently. An immediate transaction and unique running-job index serialize one opportunity, with token/lease checks before saving output. Recipient-level dispatch checks under a write transaction prevent simultaneous duplicate contact attempts across opportunities.

Leases last five minutes. Expired local work retries after 30 seconds, at most three attempts. Failed safe local jobs can be explicitly retried after ten seconds within the same limit. AI and dispatch tasks never auto-retry; external outcomes/costs may already exist. Handoff keys, unique job/draft links, event identities and acceptance links prevent repeated decisions from duplicating records.

Internal follow-up reviews accept 1–720 elapsed hours, once per message, and recheck suppression/response state when due. They never create sending permission. Owner stop/cancellation is supported; queue pressure defers due reviews by 60 seconds. UTC daily counters and elapsed-hour intervals are not Australian calendar/DST schedules. Queues are capped at 100 pending sales jobs per installation.

Emergency pause blocks new claims and sensitive POST actions while keeping opt-out/event intake and cancellation available. Requests already dispatched can finish; their outcomes are retained. Cancelling a running local task prevents new drafts/handoffs when it completes; uncertain external work is not blindly repeated. Resume may release already approved pending work: inspect/cancel unwanted work first. SQLite failures stop the worker with a diagnostic rather than claim success. There is no automatic process supervisor.

## Provider permission, costs, security and unfinished work

Amazon SES remains a **candidate**, not a verified or integrated live sender. Official AWS acceptable-use/service terms, SES documentation, ACMA, OAIC and AI pricing URLs returned outbound-proxy HTTP 403 during the Phase 5 planning review on 15 October 2026. No provider permission or current fee schedule is claimed. Before real communication, review current policies for the actual use, Australian Spam Act/privacy requirements, consent evidence, identification/unsubscribe obligations, sender authentication and operational limits. A public email address is not marketing consent; mock authorisation is not real-world consent.

Local rules, mock submission/events and tests have no external API fee. Optional AI, licensed business data, hosting, real email, monitoring and later payment processing may incur charges; none was activated or purchased. Budget estimates require verified current pricing before use. Reliable 24/7 operation needs separately approved hosting, process supervision, backups, alerts and operational incident handling.

Secrets stay in environment variables, not Git, UI fields or application logs. HTTPS verification and no-redirect behaviour remain intact. Owner actions use session authentication, ownership checks and CSRF. The mock event endpoint alone is CSRF-exempt because it requires its signature/timestamp protocol; it is not an unauthenticated live-provider integration. The application remains local-first, not production hardened: public TLS hosting, request-level rate limiting, data retention/deletion, encrypted storage/backup operations, account recovery, full legal/security review and multi-user isolation design need further work.

Original branch history and earlier documentation/results are preserved. Phase 5 defaults to a separate database and adds tables/catalogue entries. Upgrade testing uses synthetic originals/copies, including a byte-for-byte unchanged original. Never select an original customer database for development. Stop processes and make secure backups before experimenting on copies.

Remaining work includes verified live email integration/compliance, actual billed-cost reconciliation, richer local drafting/model evaluation, always-on hosting and Phase 6 website production. New invoice/payment integrations, automatic publication and revenue validation are not delivered. No real customer contact, paid API request, invoice issue, payment, website publication or public deployment occurred during this phase.

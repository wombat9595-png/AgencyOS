# AgencyOS first-sale readiness

16 October 2026 · Benji Price · Australia

**The private local workflow is implemented and tested. Gmail is NOT connected, live sending is disabled, and no real sale or payment has occurred.** This is an operating foundation, not a claim of a fully autonomous business or clearance for live outreach.

Built on production-preparation commit `8f1ad0290c240d2682bca8c924d23fb8212a1448`, on new branch **codex/agencyos-first-sale**. Existing branches/history and original databases were preserved. No new numbered development phase, purchase, cloud account or deployment was created.

## What changed and actually works

| Status | Capability |
|---|---|
| **IMPLEMENTED AND TESTED** | Private Mac-oriented launcher: one server/coordinator, same database, stable private keys, loopback binding, trusted hosts, explicit read-only old-database copy, missing-key/symlink refusal, encrypted pre-upgrade snapshots and daily backups. Linux/Python 3.13 execution verified; native Mac execution unverified. |
| **IMPLEMENTED AND TESTED** | First-customer workspace connects existing research, sales, Gmail review, questionnaire, quotes, projects, websites and invoices, retaining dashboard styling. Real receipts, owner attestations and synthetic money stay distinct. A$1,000/A$10,000/A$100,000 are goals, not forecasts. |
| **IMPLEMENTED AND TESTED** | Benji Price identity; immutable Starter A$600 / Business A$800 / Premium A$1,000 package versions. Old versions remain unchanged. GST requires an actual owner decision. Prices exclude GST if registered. Scope/revisions are limited; domains, hosting, paid assets and maintenance are separate. |
| **IMPLEMENTED AND TESTED** | Nationwide defaults, all eight states/territories, no hidden city restriction. Saved owner choices remain. Authorised manual/CSV intake, provenance, expiry checks, duplicates and qualification work. New explainable service-fit triage keeps purchase intent/budget/complexity unknown pending evidence. No nationwide leads were acquired. |
| **IMPLEMENTED AND TESTED** | Short customer questionnaire with CRM prefill, source references and owner-attested confirmation. Exact proposal inputs persist through quote, acceptance and website brief; later questionnaire edits cannot silently change them. |
| **IMPLEMENTED AND TESTED** | Three different website layouts/compositions; customer-approved services, headline, intro, about text and contact details; safe email/phone links, QA, revisions, review and ZIP export. Local export no longer lists AWS as a prerequisite. |
| **IMPLEMENTED AND TESTED** | Fixed sandboxed multi-page preview navigation. A ten-minute, read-only capability is bound to the owner/site/version/content, without sharing the dashboard cookie. It grants no account/write access. OAuth query values and preview capabilities are redacted from local access logs. |
| **IMPLEMENTED AND TESTED** | Unissued invoice-draft PDFs from accepted scope. Owner-confirmed bank receipts need accepted real scope, independent bank evidence, amount limits and a unique reference. They are attestations, not bank API verification. No money moves. |

## Gmail status and owner authorisation

**READY FOR OWNER AUTHORISATION:** Desktop OAuth, PKCE, expiring one-use state, exact account-profile check, least-privilege read scope and encrypted refresh tokens are implemented. Only **benji.price.webdesign@gmail.com** can be retained. No Gmail password is requested. The owner must configure Google and upload its Desktop OAuth client through the private screen, then sign in. See [exact setup steps](LOCAL_BUSINESS_SETUP.md#connect-only-the-dedicated-gmail).

The adapter implements supported Google HTTPS requests, token refresh, bounded recent inbox/selected-conversation reads, conservative CRM matching, opt-out suppression, correspondence handoffs, local intent hints, reply drafts/edits and audit history. Optional five-minute polling and automatic **local drafting** need owner opt-in. Disabling/disconnecting cancels pending reads. New Gmail bodies/drafts and tokens are encrypted. No attachments or remote HTML are opened; Gmail IDs prevent duplicate processing.

**BLOCKED BY EXTERNAL REQUIREMENTS:** Google project/client, explicit owner sign-in, real profile/inbox test and current Google policy/quota/verification review. All Google responses in development were mocked. The account is not connected; refresh, polling, revocation and submission have **not** been tested against a real account. Testing-mode refresh-token expiry and restricted scopes may affect unattended operation.

Reply submission is implemented but **disabled**. It needs separate `gmail.send`, current explicit recipient-consent evidence, recent owner policy/contact attestation, one exact message approval, suppression rechecks, an unpaused system and a daily ceiling. Uncertain outcomes cannot be automatically resent. The private launcher forces sending off, regardless of inherited activation variables. A receipt proves submission, not delivery. No live cold-outreach sender was installed.

**NOT YET IMPLEMENTED:** fully automatic routine sending, Gmail labels/server-side drafts, archive-wide sync, attachment analysis, verified sender identity, bounce/complaint ingestion or reliable model understanding. Rules flag pricing, requirements, revision, concern and urgency language; they are **not LLM judgement**. No unsolicited mass outreach is enabled.

## Autonomy and approval boundaries

The coordinator runs existing persistent local research/sales/Agent Center queues, handoffs, schedules, safe lease recovery, follow-up **reviews**, Sydney-date daily reports and encrypted backups. Once Google is authorised and polling opted in, it can read and locally draft. Browser closure does not stop it. **Mac sleep/shutdown or stopping the launcher stops processing**; reopening resumes durable work. No OS login item or 24/7 cloud service was installed.

Owner approval remains necessary for contact eligibility/policy, each outgoing reply, source/audit permissions, material customer requirements and scope, acceptance evidence, website review/publication, real invoice issuance, financial exceptions and independently checked receipts. Emails cannot change security settings, bank details or approvals, or execute shell commands. Interest is never acceptance.

## Builder, billing and delivery limitations

Real static websites are generated; six real browser viewports exercise all three layouts, navigation and form validation. QA is bounded static/semantic checking, not W3C conformance, WCAG certification, Lighthouse measurement or a guarantee of SEO/sales results. Arbitrary layouts, extra page types, logos/images and custom backends need further design/engineering. Keep A$600–A$1,000 work within the written scope and review profitability.

Approved email/phone links can open the customer's mail/phone app. **Preview forms do not deliver enquiries.** Agree and test a real contact solution before public use. Preview links expire; reopen the owner preview to refresh them. No public publication was performed.

Quotes use integer AUD cents and explicit GST. Acceptance is owner-attested against the exact hash/source; editable legacy statuses are not evidence. Real accepted scope can produce an **unissued draft PDF**. **Live invoice issuance remains unimplemented/gated**; invoice test approval and payment-provider flows remain synthetic. Resolve business/tax details and approve a compliant invoice process before requesting payment.

Bank receipts are owner attestations, not bank feeds. Refund/dispute/correction workflows for the new receipt ledger are not implemented. Existing signed payment/refund/dispute testing remains synthetic. No charge, transfer, refund or withdrawal is enabled. Never record an invoice, payment promise or fictional fixture as actual revenue.

## Legal/provider decisions and costs

See [owner checklist and provider review](FIRST_SALE_POLICY_REVIEW.md), separating company formation, trading names, potentially free eligible sole-trader ABN, GST, tax/invoices, consent and privacy. Benji must confirm his full legal name and actual circumstances. No ABN, company, bank detail, consent or legal declaration was invented or submitted.

**Current policy verification was blocked:** this environment's proxy returned HTTP 403 retrieving official sources. Attempt results are retained; no provider was falsely approved. Public contact data is not consent, and a dataset licence is not permission to email. Start with genuine eligible enquiries/referrals or authorised manual intake.

Additional software subscriptions: **A$0**. No AWS, domain, paid CRM, automation platform, email platform, lead data or AI API is required to run locally. Existing Mac/storage/power/internet are still used. Customer domains/hosting/assets/forms may cost money: disclose actual costs and prefer customer-owned accounts. No verified free-hosting clearance or current domain price is claimed. Bank fees depend on the account. ChatGPT/Codex subscriptions do not provide API credits.

Local AI was assessed but **not installed or tested**: Mac hardware/free disk and a specific model licence remain unknown. No model was downloaded. Templates/rules work without it; zero-cost mode blocks paid-provider and legacy AI calls.

## Exact automated validation

| Executed check | Result |
|---|---|
| Preserved baseline before changes | **235 passed** on Python 3.13.5; [log](validation/evidence/first-sale/baseline-unit.log) |
| Full final suite: `python -m unittest discover -s tests -v` | **275 passed**, 98.270 seconds, no failures/skips; [log](validation/evidence/first-sale/final-unit.log) |
| New first-sale contracts | **40 passed**; OAuth/scope/account protection, encryption, inbox/thread matching, prompt injection, approvals, uncertain sends, receipts, previews, preserved database/keys and connected 25-checkpoint journey |
| `python tests/smoke_server.py` | Passed: actual HTTP server and existing local queues/workers |
| `python tests/smoke_sales.py` | Passed: actual HTTP sales workflow, concurrent workers, signed mock correspondence and acceptance |
| `python tests/smoke_production.py` | Passed: retained strict Gunicorn/authentication, encrypted backup/restore and isolated migration |
| `python tests/smoke_overnight.py --artifacts /tmp/first-sale-overnight` | Passed: 21 local tasks, expiry recovery, schedules, process restart and pause; accelerated workload, not an overnight duration certification |
| `python tests/browser_phase5.py --artifacts /tmp/first-sale-legacy-browser` | Passed: existing UI workflow and desktop/mobile checks |
| `python tests/browser_first_sale.py --artifacts /tmp/first-sale-release-browser` | Passed: private launcher/coordinator, authenticated `/launch`, Gmail local review, questionnaire/quote and six real layout viewports; no page/HTTP 500 errors; full process restart |
| Clean pinned install + `python tests/smoke_local_setup.py` | Passed using only 13 local-runtime packages: owner login, `/launch` HTTP **200**, `/business`, disconnected Gmail, worker heartbeats and private file modes |
| `uv pip check` | Runtime/validation environment (19 packages) and clean local environment (13 packages) compatible |
| `bash -n "Launch AgencyOS.command"`, Git whitespace checks | Passed; native Finder execution remains unverified |

Executed on Linux, Python **3.13.5**, Flask **3.1.3**, SQLite **3.46.1**, Playwright **1.64.0**, actual Chromium **154.0.8037.57**. Gunicorn is validation-only and not a local runtime prerequisite. No live dependency-vulnerability database audit or provider permission certification is claimed.

[Evidence](validation/evidence/first-sale) uses fictional records, temporary databases, mocked external services and actual local processes/browsers. No real email, paid API call, invoice issue, payment, publication or business contact occurred. No MacBook was remotely accessed.

The connected journey has 25 checkpoints through qualification, mocked audit, outreach review, simulated correspondence, questionnaire, quote, acceptance, static generation/revision, QA, synthetic invoice/payment, handover, duplicates and a fresh worker. **Its first outgoing contact uses the existing mock-email provider; Gmail-specific submission is a later approved reply against a mocked API.** This is not proof of live Gmail cold outreach. Screenshots and structured browser results are retained.

## Remaining risks and shortest path to a first customer

No known failing local automated check remains at delivery; this is not production/security certification. Native Mac/Finder/Safari, real Google behaviour, current policies, live delivery and long-duration reliability remain unverified. The whole database is not encrypted: new Gmail records, bank configuration and backups are encrypted, while existing CRM/Sales correspondence and receipt evidence are protected SQLite records. Use FileVault, a protected Mac account and external backups/keys. Same-disk backups do not survive a lost Mac; retention is manual.

1. Open the [local launcher](LOCAL_BUSINESS_SETUP.md#first-opening), configure the dedicated Gmail and complete owner sign-in plus the authorised inbox check. No repetitive engineering QA is assigned to the owner.
2. Resolve legal-name/ABN/GST/contact details and communication/provider permissions. Start with one genuine eligible enquiry, not a campaign.
3. Agree one bounded package, confirm requirements, approve the exact quote and record actual customer acceptance. Review exceptions/costs before committing.
4. Build/revise and review with the customer; confirm working contact functionality and customer-owned domain/hosting arrangements.
5. Approve a compliant real invoice process, independently confirm the agreed bank payment and record it once. Approve delivery/publication separately. Reinvest actual profits before infrastructure purchases.

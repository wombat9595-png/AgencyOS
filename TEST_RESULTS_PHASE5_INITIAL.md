# Phase 5 validation

Actual execution on Linux: **Python 3.13.5**, **Flask 3.1.3**, **SQLite 3.46.1**. This is not a claim of testing on a physical MacBook, a visual browser review or public production hosting.

## Final results

- `python -m unittest discover -s tests -v`: **158 tests passed** in **49.147 seconds**. No failures, skipped tests or expected failures reported.
- `python tests/smoke_server.py`: **passed**, preserving real HTTP and separate-worker coverage for Phase 3/4 workflows.
- `python tests/smoke_sales.py`: **passed**, including the full new sales workflow and two concurrent independent worker processes.
- Dependency consistency: `uv pip check --python /workspace/.agencyos/venv313/bin/python` passed for all seven installed packages.
- `git diff --check`: passed.

The cloud Python 3.13 venv was prepared with uv outside the checkout. MacBook instructions use the normal Python.org venv/pip workflow. All test databases and data were synthetic. Mocked network/provider responses are not proof of live provider access.

## Existing functionality

The earlier 106 tests remain, covering authentication/CSRF, dashboard/CRM, imports, original quotes/invoices/projects, earlier agents, discovery policy gates, audit transport safety, Phase 4 coordination and migrations.

Three intentional compatibility assertions changed: the default database is Phase 5; the catalogue contains the six existing agents plus two working sales agents; the low-level provider transport unit test isolates transport behaviour from the new authorisation gate. Separate Phase 5 tests exercise the real gate and prove direct/queued legacy AI cannot bypass it. Existing historical-record preservation assertions were retained.

## New coverage: 52 tests

- Lead approval, research review checkpoint and research-to-outreach handoff; importing approved Phase 4 research and refusal after lead changes.
- Immutable lead/package/evidence snapshots; actual local drafts, technical-observation citations, tone/revision support and no unapproved evidence selection.
- Draft version integrity, pending-revision blocking, exact-content/sender approval, expiry and separate mock-dispatch approval.
- Explicit fictional-workflow requirement, disabled real provider selection and suppression rechecks immediately before dispatch.
- Mock acceptance distinct from real delivery; uncertain outcomes never automatically resend; recipient-level duplicate-contact controls across opportunities.
- Signed mock reply events, invalid/expired envelopes, event replay/changed-content rejection and preserved original correspondence.
- Unsubscribe, bounce and complaint handling; later delivery cannot revive suppression; queue pressure cannot discard opt-outs/originals.
- Conservative local reply classifications, owner attention, reply-draft handoffs and optional mocked AI interpretation unable to override detected opt-outs.
- Internal follow-up schedules, eligibility review, stopping on replies/opt-outs, explicit stop and no automatic sending.
- Emergency pause, cancellation during work, independent concurrent claims, one-running-job-per-opportunity and bounded local recovery versus interrupted external work.
- Shared AI transport grant enforcement, legacy direct/queued call blocking, one approved mocked request, exact approval/rate changes, expired pricing/approval, daily request/money ceilings and retained uncertain cost reservations.
- Owner-configured package/GST prerequisites, precise integer/Decimal AUD calculations, half-up line rounding and separate one-off/monthly totals.
- Readable quote correspondence excluding internal requirement-source notes; explicit current-version review and hash-bound acceptance evidence.
- Legacy Accepted status cannot create a project; repeated/stale acceptance is rejected; unreviewed proposal revisions cannot bypass accepted-scope freeze.
- Accepted project briefs use immutable quote requirements/branding, not later flow changes; late correspondence cannot regress the accepted project stage.
- Ownership, CSRF, address/header validation, agent-disable controls, repeatable migrations and a synthetic Phase 4 original remaining byte-for-byte unchanged while a copy is upgraded.

## Real HTTP and worker checks

Both smoke scripts start actual Flask processes with separate temporary databases, use authenticated HTTP forms and terminate their processes afterward.

The sales runner configures a zero-AI-budget mock sender and fictional package/leads, starts two independent workers, approves research, generates outreach, records mock acceptance, processes a signed reply and duplicate event, stops stale follow-up work, queues a reply draft, generates a proposal, calculates a GST quote, records explicitly fictional owner-attested acceptance and creates exactly one project brief. It verifies the legacy quote remains Draft, AI reservations/invoices remain zero, and pause/resume survives worker restarts.

The earlier runner exercises original login/dashboard/pages/styles, Phase 2B reviews, Phase 3 research/outreach and Phase 4 schedules, handoffs and pause. No external discovery, AI, website or email request is made by the smoke runners.

## Boundaries and limitations

- **No live email adapter:** only an explicitly named mock transport is installed. Its IDs/events/receipts are not real delivery or customer replies. Owner-recorded correspondence is separately labelled.
- **Optional AI tested with mocks only:** no paid/live AI request, real provider authentication or model-quality evaluation was performed. Shared budget controls are tested; ceilings retained in the ledger are not reconciled provider invoices.
- **Provider terms unverified:** official policy/pricing pages were blocked by the outbound proxy during planning. SES is a candidate, not an approved/live integration. SPF/DKIM/DMARC, real consent/legal review and sender verification are not established by configuration fields.
- **Acceptance is owner-attested:** no public/customer-authenticated acceptance portal or independent identity verification is installed. Tests use explicitly fictional acceptance evidence.
- No new invoice issuance, payment processing, website building, publication, public deployment, real customer contact or unauthorised data collection occurred.
- No guarantee of legal compliance, full security hardening, always-on availability or revenue. Operational hosting, backups/alerts, retention/deletion, real provider reconciliation and production review remain outstanding.

See [README.md](README.md) for MacBook installation and a safe manual walkthrough, and [PHASE5.md](PHASE5.md) for protocols, controls and remaining work. Historical results are retained in [TEST_RESULTS_PHASE4.md](TEST_RESULTS_PHASE4.md) and [TEST_RESULTS_PHASE3.md](TEST_RESULTS_PHASE3.md).

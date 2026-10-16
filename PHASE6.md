# Phase 6 — local website builder

Phase 6 adds an owner-authorized local website build path from an accepted Phase 5 project brief. It queues work on the durable Phase 5 worker and creates versioned static artifacts in additive `p6_sites` and `p6_site_versions` tables.

## What is implemented

- Local generation without paid AI, using three fixed visual themes and one-page or multi-page layouts.
- Optional AI-assisted headline/introduction writing through the existing one-use exact-request approval and AUD cost budget. Model output is limited to text fields; AgencyOS still renders fixed templates locally. AI transport was only mocked in tests.
- Business name, industry, saved requirements, branding reference, and accepted package scope are read from the saved brief/project snapshot. HTML text is escaped. Generated scripts are never executed.
- Versioned page artifacts, saved QA results, theme/revision notes, desktop/mobile previews, compare view, restore-as-new-version, and exact-version owner approval.
- Private previews run in a sandboxed iframe. The preview response applies a restrictive CSP sandbox, disables form destinations, blocks network resources and prevents access to the parent application origin/storage.
- QA checks internal navigation/page targets, required contact form fields, image alt text, language and viewport metadata, page landmarks, SEO descriptions, unsafe executable markup, missing accepted services and common unsupported business-claim phrases. Critical findings block approval.
- Testimonials are omitted because Phase 5 project briefs do not contain supplied and approved testimonial records. Address, credentials, logos, external form delivery and publication are not invented or enabled.

## Local workflow

1. Record and approve a quote and owner-attested acceptance in Phase 5.
2. Open **Website projects → Build and preview website**.
3. Choose local generation or optional AI-assisted copy, select a theme and explicitly authorize generation.
4. For AI mode, review the exact inputs and displayed maximum charge in the sales workflow and approve that one request. Leave AI budgets at zero for free local generation.
5. Start the Phase 5 worker (`python manage.py worker --phase5 --watch`) if it is not already running.
6. Inspect QA and private desktop/mobile previews. Request a supported text/theme revision or restore a prior version as a new review version.
7. Approve the exact current version for client review. This does not authorize publication.

## Validation

Synthetic Phase 6 unit/integration checks are in `tests/test_phase6.py`; the real Chromium UI workflow is included in `tests/browser_phase5.py` and produces screenshots/results under `validation/evidence/phase6/`. Run from the repository root:

```sh
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python tests/smoke_server.py
.venv/bin/python tests/smoke_sales.py
.venv/bin/python tests/browser_phase5.py --artifacts validation/evidence/phase6
```

Results and any remaining gaps are tracked in `AGENCYOS_MASTER_PROGRESS.md` and [PHASE6_FINAL_VALIDATION.md](PHASE6_FINAL_VALIDATION.md).

## Current boundaries

- No live email, invoice, charge, payment reconciliation, public deployment, client domain change, hosted contact form or external website publication is part of Phase 6.
- The built-in contact form has native required/email validation in the preview but is deliberately non-submitting. An approved client contact endpoint is required before publication.
- AI copy is unverified and may require owner edits. Current prices/model availability and actual provider billing are not verified by this feature.
- Staging/hosting integration, downloadable deployment bundles and operational website maintenance are later program milestones.


# Phase 7 — Invoices and sandbox payment reconciliation

Phase 7 adds additive `p7_*` tables and replaces the invoice navigation screen with a billing workflow. Legacy manual invoices remain available under **Historical manual invoices** and continue to use the original table. They do not count as verified revenue.

## Invoice workflow

- Create an AUD draft from an accepted Phase 5 quote, using its immutable customer, item, quantity, cycle and GST snapshot. One-off and monthly quote lines remain separate. Duplicate quote/cycle drafts are rejected.
- Business name, ABN, address, email, GST treatment, terms and sandbox provider are owner configured. The invoice GST selection must match the accepted quote.
- Approval is deliberately limited to synthetic opportunities in this build. It allocates a test invoice number and creates a static PDF carrying a prominent “SYNTHETIC TEST - NOT ISSUED TO A CUSTOMER” marking. No email, invoice issuance, or publication occurs.
- Payment instructions are omitted. No bank data is seeded or displayed. Optional bank fields require `AGENCYOS_BANK_ENCRYPTION_KEY` and Fernet encryption; stored values are never read back into the UI.
- Open invoices can create local reminder drafts. The reminder queue never sends email.

## Payment boundary

- **Local signed mock** is the default. Its synthetic checkout creates a signed event; it performs no network or bank activity.
- **Stripe test** is opt in through the provider setting and `AGENCYOS_STRIPE_TEST_SECRET_KEY`. The adapter accepts only an `sk_test_` key and synthetic invoices. It creates Checkout Sessions against Stripe's test API and uses a stable per-invoice idempotency key. This workspace has no Stripe credentials configured, and no Stripe request was made during validation.
- Stripe webhooks are checked against the timestamped `Stripe-Signature` HMAC and `AGENCYOS_STRIPE_TEST_WEBHOOK_SECRET`. Local mock webhooks use an HMAC secret and compare in constant time. No client-selected invoice status is treated as payment evidence.
- Provider events and transactions have uniqueness constraints. Repeated event IDs or transaction IDs do not create duplicate payments. Amount/currency/link validation controls paid, partial, excess/needs-review, refund and dispute states.
- Provider verified and owner reconciled payment records have different provenance. Synthetic activity is excluded from actual revenue metrics; owner-entered historical manual statuses are excluded as well.
- This implementation has no live payment adapter, live invoice issuance or bank transfer action. Do not add production bank values to the synthetic demonstration.

## Configuration

Install `requirements.txt`. Configure business identity and GST before drafting. Configure the bank encryption key only if encrypted test details are needed. Stripe test use additionally requires a Stripe test secret and webhook secret, and explicit selection of Stripe test mode in invoice settings. With no Stripe key, no external request can be made.

## Validation

See `PHASE7_FINAL_VALIDATION.md` for commands and outcomes. The deliverable `output/pdf/AgencyOS-synthetic-invoice-example.pdf` is an example only, with fictional parties and explicit synthetic labeling.

# Phase 9 — Authorized discovery and compliant outreach

Phase 9 reuses AgencyOS’s bounded discovery and sales workflows. Public or licensed source records remain distinct from marketing eligibility. All provider actions stay disabled or synthetic in this release.

## Discovery sources

- Licensed-data intake accepts owner-attested CSV records with a source identity, source and licence URLs, attribution, permitted use, reviewer, observation time and review expiry. Expired records are omitted from search and import. The app does not claim to verify licences.
- OSM discovery uses a small fixed query, attribution and a current operator policy review. It is disabled by default and stops when its policy review is missing or stale. Provider calls are bounded and rate-limited. Live discovery requires the operator to configure its own reviewed policy record.
- Duplicate candidates remain visible with explainable match reasons. CRM import requires explicit review and confirmation; possible duplicates require a second explicit acknowledgement.
- Qualification uses a deterministic score with recorded reasons. It does not predict buying intent or establish consent.

## Contact eligibility and email boundary

Sales can save an owner-attested contact eligibility record keyed by normalized email. The record contains a selected reviewed basis, an evidence reference, review time and optional expiry. AgencyOS does not store the underlying document or assert that the record is legally sufficient. A record does not authorize sending.

The existing email boundary has no live adapter. Credentials are read from environment variables only; provider event secrets are not stored in the database. Message history preserves event provenance and rejects changed-content event ID reuse. Suppression, unsubscribe language, bounce and complaint stop eligibility and pending follow-up reviews. Agents cannot clear suppressions. Exact-message approvals expire and bind recipient, sender, subject, body, provider and source draft. Mock dispatch only accepts explicitly fictional workflows with reserved example domains; it records mock acceptance, never delivery.

## Operator steps and limits

Before any future provider activation, an operator must separately verify the source licence and permitted uses, applicable outreach rules, evidence for the contact basis, provider terms, authenticated sender and operational requirements. The shipped release cannot send an email. No public discovery call, real outreach, paid AI request, payment or publication was performed as part of Phase 9 development.

Run the Phase 9 focused and full-suite validation recorded in `PHASE9_FINAL_VALIDATION.md`.

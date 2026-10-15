# Phase 4: working milestones and operational limits

## Coordination

Phase 4 adds separate persistent jobs, local schedules, activity history, budget reservations and a global pause. Inputs are immutable JSON snapshots. SQLite immediate transactions, run tokens and five-minute leases prevent overlapping workers from saving one job twice. Qualification can atomically hand its exact input snapshot to local research. Outputs require owner review. Old task tables are retained.

Named handlers are offline discovery, qualification, local research and website audit. Research/qualification is deterministic local analysis, explicitly not simulated AI. No arbitrary tools, paid model calls, emails, invoices, charges or publishing executor exists in this queue. Optional legacy AI tasks remain on their existing routes, with their existing approvals; the Phase 4 worker does not run them.

Audit approval binds exact inputs, audit-version/fetch-switch context and a 24-hour expiry. Changes/expiry return the job to approval before requests. Lead edits do not change queued snapshots. Review/cancellation decisions check current state and cannot be replayed. Failed external tasks require a newly approved task, not an automatic retry.

Expired local leases retry after 60 seconds, up to three attempts. Failed local qualification/research can be explicitly retried after ten seconds within that ceiling. Expired audit leases become Interrupted and never automatically repeat: requests may already have completed. Errors do not generate invented output. At most 100 pending Phase 4 jobs per owner. SQLite failures stop the worker with a diagnostic; restart after resolving them. Exactly-once external execution after network failure is not promised.

### Emergency pause

Stops new Phase 3/4 claims and most POST actions, including legacy agent execution. Login/logout and pause/resume remain available. Phase 4 audits also recheck before each request. Pause cannot cancel an already dispatched request or undo remote effects; an already running legacy task may finish previously started work. Completed observations remain reviewable and Phase 4 handoffs stop while paused. Resume can release queued approved work: cancel unwanted tasks before resuming.

### Spending and reports

Atomic AUD-cent reservations reject invalid/unknown costs and amounts above the daily ceiling. Uncertain reservations remain reserved. Current Phase 4 handlers reserve/record AUD 0.00; positive ceilings are rejected because no paid executor is installed. This ledger does not cover legacy Phase 3 AI endpoints. Provider pricing, paid-call integration and actual provider-cost reconciliation remain future work.

Agency Manager shows today's created tasks grouped by current status, zero-dollar reservations/actuals and the latest 100 activity records. Accounting days are explicitly UTC. This is an operational report, not revenue/conversion reporting or an immutable compliance archive. No daily email is sent.

## Australian licensed-data discovery

The new adapter ingests owner-authorised UTF-8 CSVs. It makes **no external download, scraping, geocoding or live provider search**. It retains provider name, licence URL, permitted use/restrictions, attribution, reviewer, review time and a 1–30-day expiry. This records the owner's attestation, not independent legal verification. Expiry blocks new CRM imports; re-review using a new source import preserves previous records.

All eight state/territory codes are supported: ACT, NSW, NT, QLD, SA, TAS, VIC, WA. City filters match supplied labels, ignoring case; industry filters match supplied text. Geographic accuracy and nationwide coverage depend on source data and are not independently established. Missing websites/emails remain unknown.

At most 1,000 records and 2 MB per upload. Invalid rows reject the entire batch before database writes. CRM import is a separate owner approval. It rechecks name, domain, email and imported source identity in a transaction, including previous manual/Phase 3 leads. Possible duplicates are blocked; no silent merge/overwrite. Legitimate franchises sharing names/domains may require manual investigation. Source URLs, observation times, import times and attribution remain attached to imported evidence.

### Scheduling and qualification

Offline location schedules filter reviewed staged records by state, optional city and industry. Intervals are 1–720 elapsed hours, returning 1–10 candidates per run; at most 20 active location schedules per owner. Local lead qualification/research also permits 20 active schedules. First execution is due immediately; missed intervals are skipped rather than replayed in a storm. A running Phase 4 worker is required.

Searches inspect at most the latest 1,000 matching state/city records, collapse repeated provider/ID pairs, flag CRM duplicates and recheck permission expiry. Candidates can recur until explicitly imported. No external search, automatic CRM import or marketing permission results from a schedule.

Qualification: recorded industry = 20 points; retained provenance = 30; current owner source review = 20; approved technical findings on the unchanged website within 30 days = 30. Maximum 100. Reasons and source snapshots are visible. A recent licence review does not make old business data fresh; observation dates remain visible. Scores are rules for prioritisation, not learned AI predictions, verified identities, buying intent or consent. No website URL supplied is not proof no website exists.

### Synthetic example

Save this as `fictional-businesses.csv`. These are fictional fixtures, not discovered customers:

```csv
source_id,source_url,observed_at,business_name,state,city,industry,website,email,contact_name
synthetic-001,https://example.com/synthetic/001,2020-01-01T00:00:00+00:00,Fictional Studio NSW,NSW,Sydney,Design,,,
synthetic-002,https://example.com/synthetic/002,2020-01-01T00:00:00+00:00,Fictional Studio WA,WA,Perth,Design,,,
```

In Licensed discovery use provider `Synthetic development fixture`, licence URL `https://example.com/synthetic-terms`, intended use `Fictional local testing only`, attribution `Synthetic test records`, your reviewer name and a review duration. The attestation concerns your own test data; it does not approve example.com or a real provider. Stage, filter, review and approve a candidate. Never use fictional permission records to enable real services.

Required columns: `source_id,source_url,observed_at,business_name,state,city,industry`. Optional: `website,email,contact_name`. Timestamps need a timezone and cannot be future dates. Do not invent real-source observation dates. Store only records whose licence permits the intended commercial CRM storage/use.

## Website Audit Agent

The audit engine performs real HTTP/static HTML checks through the existing DNS-pinned, certificate-verifying HTTPS transport. It records response statuses, observation times, content SHA-256 hashes, metadata, viewport content and mailto/tel anchors. Findings refer to source observations; recommendations are separate. Only owner-approved audit output becomes selectable evidence in existing research.

- One chosen HTTPS page plus up to five unique one-hop HTML links on the same origin; no complete crawl.
- At most seven requests including robots.txt. Maximum 512 KiB per HTML response and 64 KiB robots. Roughly 120 seconds overall, existing 15-second individual fetch deadline and at least one second between requests.
- At most 100 audit requests per UTC day per database and 20 runs per URL/day, at least 60 seconds apart. Failed requests count. Independent databases do not coordinate limits.
- Robots checked on every path. Unknown restrictions fail closed. Slower crawl-delay/request-rate requirements are refused. Robots allowance is not legal authorisation.
- No redirects, credentials, custom ports, query URLs, external links, downloads, JavaScript or third-party assets. HTML base URLs are respected for link resolution. Excluded/unperformed checks stay visible.
- All DNS results must be public. Connections pin a validated address while checking TLS certificates/hostnames. Control characters and backslashes are rejected. Outbound-proxy mode is refused rather than bypassing network restrictions.

HTTP 404/410 findings concern the requested path, not the entire business site. Successful verified HTTPS establishes HTTPS for that request, not a security guarantee. TLS/network failures and blocked redirects are not proof a site is down. HTTP-only inputs are rejected; explicitly enter and approve an HTTPS counterpart to test it. Plain HTTP upgrade behaviour is not tested.

Missing metadata/viewport findings concern retrieved HTML only. Content quality, mobile rendering and conversion impact are not inferred. Missing mailto/tel anchors is an observation, not proof of missing contact information: forms, text, images and other pages may provide it. No JavaScript, speed, SEO ranking, complete accessibility or whole-site security test occurs. UTF-8 decoding replaces invalid bytes; complex encodings remain a limitation.

### Live audit prerequisites (not activated during development)

The owner must confirm permission for the exact origin and selected paths, have a supported direct network that enforces destination checks, set `AGENCYOS_WEBSITE_FETCH=1` in both app/worker shells, then approve a prepared audit. The switch alone is not permission. This cloud environment's outbound proxy is unsupported. Never remove a required platform proxy or weaken TLS/DNS checks to make a request succeed. A safe proxy-aware fetch service remains future integration work.

## Provider policies, costs and legal boundaries

No online nationwide provider is selected as verified. Official policy/pricing pages returned proxy HTTP 403 during planning on 15 October 2026. Public OSM endpoints remain separately permission-gated; they are not this release's scaling strategy. Before choosing a dataset/API, verify commercial prospecting/CRM use, retention, derivatives, attribution, privacy, deletion and redistribution terms, plus actual Australian coverage. An import attestation does not enable live discovery.

New local rules/imports and mocked tests have no external API fee. Real audits use network traffic and existing host resources. Licensed data and later AI, hosting, email and payment integrations may cost money; none is contracted or activated here. Future fees need separately approved integrations and account-side limits.

Public data, an email address, qualification scores and audit findings are not marketing consent. No new sending, charging, invoice issue or publishing executor is included. Later milestones must establish applicable Australian Spam Act/privacy obligations, provider permissions and separate owner/customer approvals. Production data retention/deletion policy, recovery controls and a security review remain outstanding. New records use authentication, ownership checks, CSRF and escaped rendering; this is not a claim of complete legal compliance or production hardening.

## Preservation and remaining work

Phase 4 defaults to its own database; tests use temporary synthetic files. Migrations add tables and perform a one-time audit catalogue upgrade, preserving later agent enable/disable choices. Older records and source history remain in Git; README_PHASE3.md preserves the original documentation. Back up stopped databases outside Git before experimenting on copies. No original customer database was selected or migrated during development.

Browser-independent processing works while the worker runs. Always-on hosting/service supervision, automated backups/alerts, Australian calendar-based scheduling, proxy-aware audits, independently verified provider integrations and nationwide live coverage are not delivered. SQLite remains a local single-host system. Later milestones—email delivery, client acceptance, website generation, new financial integrations, payment and publication—remain future work.

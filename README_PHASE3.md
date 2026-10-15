# AgencyOS — Phase 3: source-based discovery, research and outreach

A local-first Flask/SQLite agency workspace. Phase 3 preserves login, dashboard, CSV Lead Finder, duplicate review, Phase 2B Agent Control Center and saved tasks, quick outreach drafts, quotes, invoices and projects, with the existing visual design.

**Delivery status:** the OSM discovery adapter and approval workflow are implemented, but **live discovery is disabled by default**. Current provider policies could not be verified from the development environment: official sites returned proxy HTTP 403 on 15 October 2026. No live business search or paid AI call was performed. Tests use fictional businesses and mocked external services. No fake live results or demo businesses are inserted into your database.

## Install on your MacBook

Download branch `agencyos-phase3` using GitHub's **Code → Download ZIP**. Extract into a **new folder**; keep your old application and databases intact. Requires Python 3.13; if needed, install it from [python.org](https://www.python.org/downloads/macos/).

Open Terminal in the extracted project folder:

```sh
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
mkdir -p .development
export AGENCYOS_DB="$PWD/.development/agencyos-phase3.db"
export AGENCYOS_SECRET_KEY="$(python -c 'import secrets; print(secrets.token_hex(32))')"
python app.py
```

Open `http://127.0.0.1:5000/setup`, create a development owner account, then sign in. Start with fictional leads. The app binds to your Mac only. Keep Terminal open; Control+C stops the server. If port 5000 is occupied, set `export PORT=5001` before starting and use that port in your browser.

Without `AGENCYOS_DB`, Phase 3 defaults to `.development/agencyos-phase3.db`, not the Phase 2A or Phase 2B database. An explicit `AGENCYOS_DB` always selects that file, so **do not point it at your original database**. Without a secret key, the app generates a private process-specific key; a restart signs you out. For ongoing use, supply a strong stable secret securely. No `.env` loader is included.

## Start the Phase 3 worker

The worker is a separate local process that performs queued work. Open a **second Terminal**, move into the same project folder, and run:

```sh
source .venv/bin/activate
export AGENCYOS_DB="$PWD/.development/agencyos-phase3.db"
python manage.py worker --watch
```

Set the same optional provider and policy variables in BOTH Terminals before starting their processes. The worker must use the same database as the app. A provider/configuration mismatch requires fresh approval rather than making a call with different settings.

For a single job instead of continuous polling:

```sh
python manage.py worker
```

The worker makes no automatic email, payment or publishing action. It does not create recurring jobs or invent tasks. `--watch` executes tasks you explicitly queued/approved. Stop with Control+C; do not run it if you do not want approved queued jobs to execute.

## Working workflows

### 1. Business discovery (policy verification required for live calls)

Open **Business Discovery**. Enter a city/region and country (Canberra, ACT, Australia is prefilled), industry, and 1–20 maximum candidates. You may search anywhere, subject to source coverage. Optional targeting: business-name keyword and whether a usable website URL is listed.

A task is prepared without a network request. After provider setup, review and approve its input; the worker resolves the place using Nominatim, then queries a **10 km radius around the resolved centre** using Overpass. Results show the resolved location/centre, source record links, retrieval timestamps, attribution and potential duplicates. At most 60 matching OSM records are examined; filtering may yield fewer candidates than requested. This is not an exhaustive search of a city, region or industry.

Supported aliases map to explicit OSM tags: plumbing (`craft=plumber`), landscaping (`craft=gardener`), electricians, cafes, restaurants, dentists, hairdressers and builders. A custom documented `craft`, `shop`, `amenity`, `office` or `healthcare` tag may be supplied. Category aliases are search interpretations of tags, not independently verified business classifications. Arbitrary Overpass queries are not accepted.

Candidates stay outside the leads table until you explicitly approve each import. Duplicates are flagged by name, email/domain and source identity; they are rechecked at import, in a transaction. Intentional duplicates require an additional approval. Completed decisions cannot be replayed. No candidate overwrites an existing lead. Missing addresses, email and website fields stay unknown; a missing source website is **not proof that the business has no website**. No email addresses are guessed.

#### Confirm policies before enabling live discovery

The shipped default is disabled. Read [PROVIDER_POLICIES.md](PROVIDER_POLICIES.md), verify the current policies and intended CRM use yourself, and obtain any required permission. If review is unavailable or terms do not permit the planned usage, **leave it disabled**.

After actual verification, record your attestation (substitute your name and a real operator contact; these are not API secrets):

```sh
python manage.py policy-review \
  --reviewer "Your name" \
  --contact "your-contact@example.com" \
  --i-have-verified-current-policies
export AGENCYOS_OSM_POLICY_FILE="$PWD/.development/osm-policy.json"
```

This command records **your** review. It does not fetch policies or verify them automatically. It refuses to overwrite an existing review file. For a later review, choose a new `--output` filename and update the environment variable. Records expire after 30 days; changes invalidate existing discovery approval.

Default endpoint limits are conservative application ceilings, **not a claim that current provider terms allow every search**: minimum two seconds between requests per service, maximum 20 requests per service per UTC day, 24-hour location cache, one-hour query cache, 20-second provider network timeout and 2 MB response limit. The review command accepts a longer `--interval` (up to 60 seconds) and lower `--daily-limit`. If policies require other limits or terms the implementation cannot satisfy, do not enable that public endpoint. Use an appropriately permitted service through a separately reviewed adapter instead.

A real operator contact identifies the app's requests. HTTP 429/503 blocks further service calls for an hour; there is no automatic retry. If you run multiple independent databases/app installations, their local usage counters do not coordinate: run a single worker/database for this small-scale public-service configuration. Provider-side restrictions take precedence.

**Attribution:** © OpenStreetMap contributors, [ODbL 1.0](https://www.openstreetmap.org/copyright). Source links, retrieved dates and attribution are retained with candidates and imported evidence. Preserve attribution when copying/exporting records. Public redistribution of an adapted database may require ODbL share-alike compliance. Source visibility does not grant marketing consent or remove privacy obligations.

### 2. Evidence research

From a lead, open **Evidence research**. You can:

- Use saved lead fields only; the report will say no external source was inspected.
- Add an authorised source URL and exact quote manually. It is labelled **Owner supplied**, not independently verified. Its timestamp is the submission time, not a claimed historical observation date.
- Prepare an optional public HTTPS homepage inspection. Confirm permitted use, then separately approve the task. Set `AGENCYOS_WEBSITE_FETCH=1` in both shells only after confirming authorised use.

Website inspection fetches robots.txt and at most one HTTPS homepage. It respects robots restrictions, rejects redirects, custom ports, credentials, private/reserved IPs and internal destinations, pins the connection to a validated public IP while checking the TLS hostname/certificate, and bounds size/time. It refuses operation with an outbound proxy because safe destination pinning cannot then be guaranteed. It does not bypass site restrictions. Robots permission alone is not legal authorisation.

The tool records the actual source URL, timestamp, content hash, title, H1, description, HTML language and a bounded visible excerpt. UTF-8 decoding is used, with replacement for invalid bytes. No JavaScript runs; it does not measure page speed, accessibility, SEO rankings or whole-site quality. Failures create no quality diagnosis. A missing tag is reported only as absent from the retrieved homepage HTML at that time.

Inspect results require approval before their evidence becomes selectable for research. Directory evidence is marked as source-reported; manual quotes are labelled owner-supplied. Select up to 10 evidence items and choose local analysis or AI suggestions. Inputs are saved as an immutable snapshot. Source observations, recorded lead details, suggestions, questions needing verification and possible outreach angles are displayed separately.

AI never creates the source observations. Its suggestions must reference real selected evidence IDs or be labelled general advice with no supporting source; invented IDs and malformed structured output fail the task. Model suggestions can still be wrong: check them before approving. There is no automatic fact checker or guarantee of truth.

### 3. Approved research → saved outreach

Approve a research result, then choose **Prepare draft from this research**, or open **Research-based drafts** from the existing outreach page. Choose local drafting (no provider cost) or an approved AI request. Local drafts use actual inspected titles when available and otherwise make no inspection claims.

Every generation produces a separate saved draft linked to its approved research snapshot. Review it as Needs review, Approved or Rejected; optionally set a **manual follow-up review date**. History records each review. The original quick template/AI drafts page remains available; legacy quick AI drafts now also require explicit approval of charges/data sharing, but only the new research-based flow stores history.

No draft is sent automatically. Follow-up suggestions are reminders to review suitability/consent, not scheduled messages. Future sending must implement applicable consent/legal requirements, unsubscribe handling, suppression lists, rate limits and explicit authorisation of exact recipients/content. Nothing here guarantees customer acquisition or revenue.

## AI provider configuration and charges

Local analysis/drafting and manual/CSV workflows require no AI provider. Live AI research/drafts use the existing HTTPS OpenAI-compatible chat-completions adapter. Configure in both app and worker shells:

- `AGENCYOS_AI_PROVIDER=openai-compatible`
- `AGENCYOS_AI_ENDPOINT`: your approved full HTTPS chat-completions endpoint
- `AGENCYOS_AI_MODEL`: your approved compatible model
- `AGENCYOS_AI_API_KEY`: your private credential

Do not put keys in code, task briefs, source evidence, screenshots or chat. No keys are saved in task records. A private configuration fingerprint invalidates approval if provider settings or the key change. HTTPS verification is preserved; API redirects are rejected, response size is bounded, and errors avoid exposing keys/raw provider responses.

For example, OpenAI's chat-completions endpoint is `https://api.openai.com/v1/chat/completions`; select a compatible model and confirm your account access and current pricing. API billing may be separate from a chat subscription. No account was connected or charged during development.

Phase 3 AI tasks need explicit approval of their full input snapshot and potential charge. Maximum 20 Phase 3 AI calls per database per UTC day, one call per job, no automatic retry, task inputs at most 24,000 serialised characters, up to 900 output tokens for research and 600 for drafts. These are usage ceilings, **not an exact dollar spending cap**. Set provider-side spending controls where available. Review charges before replacing interrupted/failed jobs. Existing Phase 2B research/quick draft routes retain their separate original limits; Phase 3's daily counter is not an account-wide billing meter.

## Queue reliability and future automation

Jobs have real persisted states, progress stages and event history:

`Awaiting approval → Queued → Running → Awaiting review → Approved / Rejected`

Local jobs may enter Queued directly. Unstarted jobs may be Cancelled. Failures end Failed. Workers claim jobs transactionally; overlapping workers cannot claim the same queued job. Completion, candidates/evidence/drafts and task status are committed together. A result is not persisted after its worker loses the lease. Queue views show the latest 100 jobs.

A worker crash may leave an uncertain external request. After its five-minute lease expires, the next worker pass marks it **Interrupted**, never automatically requeues it. Check provider usage and explicitly create/approve a replacement if needed. This is an **at-most-once attempt policy**, not guaranteed completion or guaranteed exactly-once behaviour at an external service. No automated retry makes a second potentially charged call.

Phase 3 adds `not_before`, registered task handlers, transaction-based claims, usage reservations and independent worker execution as foundations for scheduling and future multi-agent work. There is **no enabled scheduler** and no arbitrary model tool execution. Lead discovery and saved outreach are functional flows, subject to configuration. Website builder, project manager and full audit agents remain clearly planned. Phase 2B tasks remain available on their existing routes; they are not silently converted into queued Phase 3 tasks.

The old email/spending/publishing approval records remain record-only; no executor exists even for approved proposals.

## Database backups and compatibility

Your original database was not supplied and was not used during development. All tests use separate temporary synthetic databases.

Stop the old app and worker before backing up. Use SQLite's backup mechanism if WAL/journal files exist. For a cleanly stopped database, a copy such as this is suitable (run in the old folder):

```sh
cp -p agencyos.db agencyos-before-phase3.db
```

Keep backups securely outside Git. To evaluate real records later, approve that use yourself, copy a backup into the **new** folder and point `AGENCYOS_DB` at the copy. Keep the original untouched. Do not run old/new applications concurrently against one database.

Migrations add Phase 3 job, event, candidate, evidence, draft/history, cache, usage and migration tables. They do not drop/recreate core tables or erase Phase 2B tasks/results. Existing Lead Discovery/Outreach planned entries are upgraded once; user settings are retained thereafter. Evidence/drafts retain their snapshots if a lead is later deleted; nothing restores a deleted lead silently.

Passwords, keys, databases, caches, review/contact files, virtual environments and ZIPs are excluded from Git. Test credentials are fictional fixtures, never real account credentials.

## Manual and CSV Lead Finder

The original manual leads and CSV import/review workflow remains available even without live discovery or AI. CSV: UTF-8, up to 1,000 leads and 2 MB request size, required `business_name`; optional `contact_name,email,website,industry,location,source,notes,status`. Download a sample inside Lead Finder. Review invalid rows and possible duplicates before confirmation. Websites must be HTTP/HTTPS without embedded credentials. Lead search, filtering, status changes and quick outreach links are preserved.

## Tests and verification

```sh
python -m unittest discover -s tests -v
python tests/smoke_server.py
```

Tests use fictional records and mocked discovery, website and AI responses. They cover existing login/dashboard/leads/quotes/invoices/projects/Phase 2B tasks, policy gating, API request/response parsing, cache/quotas/backoff, candidate duplicates and approvals, evidence provenance, AI reference validation, immutable snapshots, saved outreach reviews, queue ownership/concurrency/interruption, errors, SSRF restrictions and migration preservation. Python 3.13 now reports unclosed SQLite connections; test fixtures were updated to close them explicitly.

The HTTP smoke test starts the actual local server on port 5057 using a temporary database, verifies the original workflows and invokes the real worker in a separate process for local research and saved drafting. It stops the server and removes its synthetic database afterward.

See [TEST_RESULTS.md](TEST_RESULTS.md) for the final verified versions and counts. Live provider operation and browser visual testing are not claimed.

## Boundaries

This is a single-owner local app, not a public production service. No deployment, payments, sending or website publication is included. Directory coverage and records may be incomplete/outdated. Missing contact information remains unknown. No autonomous revenue guarantee is possible. Before public hosting, add a security review, robust recovery, rate limiting, audit controls and production deployment configuration. The existing optional Google Fonts styling is retained; local fallback fonts work offline.

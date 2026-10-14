# AgencyOS — Phase 2B Agent Control Center

A local-first Python/Flask/SQLite agency workspace. The existing dashboard, owner login, manual leads, review-only outreach, quotes, internal invoice records, and website projects remain available. The existing dark visual identity is retained.

## Phase 2 features

- Dedicated Lead Finder CSV upload with validation, source attribution and an import preview.
- Explicit confirmation before saving leads. Invalid rows are rejected individually; valid rows can still be imported.
- Duplicate hints against existing leads and earlier valid CSV rows, based on normalised business names, case-insensitive email addresses, and website domains (ignoring `www.`).
- Likely duplicates are unselected by default. To import one intentionally, select both its import checkbox and its duplicate approval checkbox.
- Confirmation rechecks duplicates against the current database, runs in a transaction, and consumes the preview so it cannot be imported twice. New duplicates without approval are skipped.
- Final imported, rejected and skipped counts; row-specific validation messages appear in the preview.
- Lead search across business/contact names, email, website, industry, location and source; exact filters for status, industry, location and source.
- Lead status updates, source/date display, and direct links to existing outreach drafts.
- Optional configurable OpenAI-compatible AI draft adapter; no automatic emails, scraping, payments or publication.
- CSRF protection for all POST forms, upload limits and escaped preview content. Financial inputs now reject non-finite or oversized amounts safely.

## Install and run on your MacBook

Requires Python 3.10 or newer. Open Terminal in the updated AgencyOS folder:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
export AGENCYOS_SECRET_KEY="$(python -c 'import secrets; print(secrets.token_hex(32))')"
mkdir -p .development
export AGENCYOS_DB="$PWD/.development/agencyos-phase2b.db"
python app.py
```

Open `http://127.0.0.1:5000/setup` to create a development owner account. Then sign in. This command uses a separate development database and does not touch a Phase 1 database. Keep the terminal open; Control+C stops the server. `PORT` can change the default port 5000.

The secret key controls signed sessions; use a strong stable private key for ongoing use. If no secret key is configured, Phase 2B generates a private random session key for the current process; restarting then signs you out. There is no shared hard-coded session key. Never commit secret values. No `.env` loader is included: export variables in the shell that starts the app.

### Existing data and migrations

The uploaded project did not include `agencyos.db`, so no original customer records were available or used during development.

Do not overwrite or delete your original database. First stop the old application and back up its database. For example, from the old application's folder:

```sh
cp -p agencyos.db agencyos-before-phase2.db
```

If SQLite journal/WAL files exist, use SQLite's backup mechanism or ensure a clean shutdown before copying. Keep the backup securely outside source control.

To check compatibility without modifying the original, copy that backup into the updated project's `.development` folder, export `AGENCYOS_DB` to the copy, and start the updated app. Using real customer data requires your approval; the automated tests use synthetic data only.

On startup, an idempotent additive migration adds `location` and `source` columns to `leads`, a status index, and a `lead_imports` table for previews. It preserves existing IDs, values, timestamps, account password hashes, quotes, invoices and projects. Existing source/location fields remain blank; the UI labels blank sources as legacy records. It never deletes the database or recreates existing tables. Back up before any migration. If later restoring the Phase 1 app, use the preserved original database/backup; Phase 1 can otherwise read the added lead columns but lacks the new workflow.

Phase 2B defaults to `.development/agencyos-phase2b.db`, separate from the Phase 2A `agencyos.db` and `agencyos-dev.db` files. `AGENCYOS_DB` still selects an explicit database path. Do not point it at your original database; test with a backed-up copy only when you approve using those records.

## Phase 2B — Agent Control Center

Download branch **agencyos-phase2b** into a separate folder; leave your Phase 2A folder and database intact. Use the MacBook commands above to run the new version with its separate development database. Create a new development owner account and use synthetic leads initially.

### First agent: Lead Research

1. Sign in and add or import a synthetic lead.
2. Open **Agent Control Center** in the sidebar. Rename, enable or disable the Lead Research Agent as needed.
3. Click **Assign a task**, select the lead, enter a title and optional brief, and choose **Local suggestions** or **AI model**. You can also click **Research lead** in the lead list.
4. Local tasks are queued; click **Run task**. Local analysis makes no external requests and needs no AI key.
5. AI tasks first show **Awaiting AI approval**. Review the exact saved fields, brief, provider endpoint and model; approve the data sharing and potential charge for **one** model request, then click **Run task**. Task creation and approval alone make no model request.
6. Review the result and choose **Approve result** or **Reject result**. Approving a result does not approve any email, purchase or website publication.

The agent analyses a saved snapshot of business name, website, industry and location, plus your brief. It never changes the lead. Stored email address, contact name and notes are excluded. Your brief is sent in AI mode, so do not put private information in it. Editing or deleting a lead later does not alter a task's approved snapshot.

Local mode produces recorded facts, planning suggestions and limitations. AI mode requests recommendations and verification questions from your configured model. Neither mode fetches or audits a website. A recorded website URL is not evidence of site quality. AI output may still contain mistakes; always check its claims before use. Output is displayed as escaped plain text, never interpreted as commands or executable HTML.

### Progress and task safety

The task list supports status filtering and links to task details. Each task has progress and a timestamped event history:

`Queued → Running (25%) → Awaiting review (100%) → Approved or Rejected`

AI tasks require approval before entering Queued. Failures end in Failed; unstarted tasks can be Cancelled. Progress shows stages, not live token streaming or an estimated completion time. Execution happens during your **Run task** request, not in a background scheduler. You may open the task in another tab and refresh to monitor it. Task details include a refresh button; the server supports concurrent requests.

Repeated/concurrent Run clicks cannot run the same task twice. Failed tasks are not automatically retried; explicitly create another task if needed. Changed provider, endpoint, model or API credential invalidates a queued AI approval. If the app stops mid-run, its task may remain Running. After two minutes you can explicitly mark an interrupted run Failed. Check provider usage before creating a replacement: an earlier AI request may already have been charged. Do not mark a genuinely active request interrupted.

### Separate action approvals

After approving a result you can record an exact **email**, **spending** or **publishing** proposal and approve or reject it separately. Decisions and timestamps are retained in the task history. A decision cannot be silently changed by repeating a request.

**These are approval records only. No email, payment or publishing executor exists.** Even an approved proposal does not execute anything. Model text cannot approve actions, select tools or change task states. Future executors must validate ownership and a fresh approval of an exact structured action, including recipient/content, amount/currency/vendor or destination/artifact; these descriptive records alone must not be treated as executable authorisation.

The first agent is runnable. Lead discovery, website audit, outreach, website builder and project manager cards are explicit **planned** entries and cannot be enabled or assigned work yet. Existing Phase 2A outreach drafts remain available on their original page. Adding a future runnable agent requires a developer to implement and register its handler and approval policy; changing a database row does not create a working agent.

### Real AI integration

The same HTTPS OpenAI-compatible connection serves outreach and lead research. Supply the four `AGENCYOS_AI_*` variables documented below in the shell that starts the app. No keys are stored in source or task records; task approvals store only a configuration fingerprint. Never put API keys in task briefs or the database.

For example, if you explicitly choose OpenAI API access and approve its pricing, its chat-completions endpoint is `https://api.openai.com/v1/chat/completions`; use an available compatible model such as `gpt-4.1-mini`. Enter your own API credential securely in Terminal, not in code or chat. API usage can require separate billing from a chat subscription. No live provider was contacted during development, and your account/model access remains unverified.

Requests preserve HTTPS certificate checks, reject redirects, limit response size and use a 20-second network timeout. Research requests cap output at 900 tokens. The cap does not guarantee a dollar price or total provider usage. Invalid configuration prevents approval; provider errors fail the task safely without exposing secrets or raw responses. There is no automatic retry.

### Database compatibility

Phase 2B adds `agents`, `agent_tasks`, `agent_events` and `agent_approvals` plus a task index. Seed agents are inserted only if missing, preserving renamed agents, settings and existing task history. The migration does not reset or drop any Phase 2A records. Tasks and event/approval history persist in the selected database across restarts; processes and live calls do not. Result/snapshot data can include business information, so protect database backups. There is no task deletion/export UI yet.

## Lead Finder CSV workflow

Sign in, open **Lead Finder**, and download the sample CSV. Supply a source label and upload a UTF-8 comma-delimited file (UTF-8 BOM is accepted).

Supported headers:

```csv
business_name,contact_name,email,website,industry,location,source,notes,status
Synthetic Studio,Alex,alex@example.com,https://example.com,Design,Sydney,Authorised research,Review manually,New
```

`business_name` is required; all other columns are optional. Header names may use spaces or underscores and are case-insensitive. Unknown or repeated columns are rejected. Empty email/website fields are allowed. Supplied email addresses must have a basic valid structure; websites must be HTTP/HTTPS URLs without embedded credentials. Text fields are limited to 254 characters, notes to 4,000. Industry/location are free text, not verified categories or addresses. Supported statuses: New, Contacted, Interested, Client, Not a fit. Blank status defaults to New. Blank per-row source uses the upload source label.

Limits: 1,000 lead rows, 2 MB total request size. Oversized files, bad encodings, malformed quoting or unsupported headers are rejected without creating leads. Invalid individual rows remain visible with reasons. CSV row numbers in the preview count data rows, not physical lines (quoted multiline notes may span lines).

Review the preview, select valid rows, approve intentional duplicates where appropriate, and confirm. The result reports imported, rejected (invalid), and skipped (unselected/duplicate) rows. Uploading alone never modifies the lead table. Previews belong to the signed-in owner, expire after one hour, and are removed on confirmation. Cancel returns without importing; expired previews are cleaned up during subsequent uploads. Preview data is stored in the selected SQLite database, so protect backups accordingly.

Duplicate checks are conservative hints, not proof: distinct businesses may share a name/domain, and spelling variations may evade detection. Rows are never silently merged or used to overwrite existing leads. Search filters combine with AND; clear filters to see all records. Existing manual entry and deletion remain available.

## Outreach and optional AI configuration

Use **Draft email** on a lead. Template drafts run locally without credentials. Selecting AI without configuration shows a clear error. Neither option sends email; copy and review drafts before using them elsewhere.

The optional provider uses the OpenAI-compatible chat-completions request/response format. Before enabling it, choose and approve a provider and any costs yourself. Configure these environment variables securely:

- `AGENCYOS_AI_PROVIDER`: `openai-compatible`
- `AGENCYOS_AI_ENDPOINT`: full HTTPS chat-completions endpoint
- `AGENCYOS_AI_MODEL`: the provider's model identifier
- `AGENCYOS_AI_API_KEY`: your private credential; never put it in source or chat

No default paid endpoint/model is configured. No external AI calls were made in development. AI is invoked only after you select AI draft and submit the form. It sends business name, contact name, industry, location, website, your offer and tone to the configured provider. It does not send the stored email address, source or notes. Approve this data sharing before using real leads. HTTPS verification remains enabled, redirects are rejected, and requests time out after 20 seconds. Configuration, network, HTTP and malformed-response errors are shown without exposing keys or provider response bodies. API keys are read from the process environment, not stored in SQLite. Review every generated claim; AI output is not verified research.

## Tests

From the project folder with the virtual environment activated:

```sh
python -m unittest discover -s tests -v
python tests/smoke_server.py
```

The unit/integration tests create isolated temporary SQLite databases with synthetic data. They cover login/logout and CSRF, all workspace pages, lead entry/deletion, quote relationships and money, invoice/project status changes, template outreach, CSV validation/preview/confirmation, duplicate review and rechecking, replay/expiry/owner isolation, filters/statuses, escaped content, additive migration preservation, and mocked AI success/errors. They never call a paid provider or touch the default database.

The HTTP smoke check starts the actual Flask server on port 5057 with a temporary synthetic database, exercises owner setup, login, lead creation, dashboard, all workspace pages and CSS, also runs a local agent task through assignment, execution, result review and action-proposal rejection, then stops it and removes its data. Leave port 5057 free when running this check.

Validated in the cloud with Python 3.12 and Flask 3.1.3: 39 automated tests passed, plus the real HTTP smoke check. Phase 2B tests additionally cover agent settings, task state transitions, required AI consent, changed-configuration reapproval, concurrent/repeated runs, provider failures, result review, separate action decisions, owner isolation, CSRF, escaped output, interrupted-run recovery, snapshots and migration preservation. No browser visual testing, live AI provider testing or original customer-database testing was performed.

## Remaining limitations

This is a single-owner local development app, not a production deployment. There is no password reset, comprehensive security audit trail, fuzzy duplicate scoring, automatic lead scraping, message sending, payment processing, public hosting or automated site generation. Quotes/invoices remain internal records, not tax invoices or payment collection. CSV validation does not verify deliverability, website ownership or consent. Previews are bounded but rendered in one table; there is no pagination. Large existing lead databases may make duplicate checks slow.

Before public deployment, add rate limiting, HTTPS, production secret management, account recovery, audit logging and a security review. The app binds only to loopback by default. External Google Fonts are retained from Phase 1; fallback fonts apply offline. Dependencies retain the existing Flask version range rather than a new lockfile.

# AgencyOS — Phase 5: coordinated sales workflow

The master development program is tracked in [AGENCYOS_MASTER_PROGRESS.md](AGENCYOS_MASTER_PROGRESS.md) and [AGENCYOS_MASTER_ROADMAP.md](AGENCYOS_MASTER_ROADMAP.md). Phase 6 website delivery is described in [PHASE6.md](PHASE6.md), Phase 7 billing/payment boundaries are in [PHASE7.md](PHASE7.md), and Phase 8 operations are in [PHASE8.md](PHASE8.md). Current milestone status and validation evidence are recorded in the progress log.

Built from Phase 4 commit `d55468a`, preserving the dashboard styling, earlier modules and records. Phase 5 connects approved research, outreach drafts, correspondence, internal follow-up reviews, proposals, versioned AUD quotes and owner-attested acceptance/project briefs.

**Live email is disabled: no live sender adapter is installed.** The email provider is explicitly a mock for testing the integration boundary. Local agents perform real work on saved records; they do not claim simulated business discoveries, replies or customer agreements. Optional AI writing/interpretation is implemented behind exact-request approval and budgets, but was validated only with mocked provider responses. Default AI budget is zero.

**Final validation:** automated browser, server/worker and regression testing is recorded in [PHASE5_FINAL_VALIDATION.md](PHASE5_FINAL_VALIDATION.md). You do not need to repeat the walkthrough to validate this release.

## MacBook installation — new folder and database

Install Python 3.13 from [python.org](https://www.python.org/downloads/macos/) if `python3.13 --version` is unavailable. Git may prompt you to install macOS command-line tools. Keep all older folders/databases unchanged.

```sh
git clone --branch agencyos-phase5 --single-branch https://github.com/wombat9595-png/AgencyOS.git AgencyOS-Phase5
cd AgencyOS-Phase5
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
mkdir -p .development
export AGENCYOS_DB="$PWD/.development/agencyos-phase5.db"
export AGENCYOS_WEBSITE_FETCH=0
export AGENCYOS_AI_PROVIDER=""
unset AGENCYOS_OSM_POLICY_FILE
python app.py
```

Alternatively download the Phase 5 branch ZIP into a **new** folder, open Terminal there, and begin at the venv command. No API key is needed for the local workflow.

The app prints its local address; open its `/setup` path, create a development owner account and sign in. It binds to your computer only. If port 5000 is occupied, set `export PORT=5001` before starting. A private in-memory session key is generated; restarting signs you out. Persistent sessions require a securely supplied `AGENCYOS_SECRET_KEY`. `.env` files are not automatically loaded.

The default database is `.development/agencyos-phase5.db`. An existing `AGENCYOS_DB` overrides that default: do not point it at an original customer database. Use a backup copy only for migration trials.

## Start the sales worker

Open a second Terminal in your new Phase 5 folder:

```sh
source .venv/bin/activate
export AGENCYOS_DB="$PWD/.development/agencyos-phase5.db"
export AGENCYOS_WEBSITE_FETCH=0
export AGENCYOS_AI_PROVIDER=""
unset AGENCYOS_OSM_POLICY_FILE
python manage.py worker --phase5 --database "$PWD/.development/agencyos-phase5.db" --watch
```

The app and worker must use the same database. `--phase5` processes sales work and internal follow-up reviews. Existing `--phase4` remains available for Phase 4 research/audits; no phase flag selects the legacy Phase 3 queue. Do not combine phase flags.

Browser closure does not stop the worker. Keep both Terminal processes running and your Mac awake; no always-on service is installed. Stop with Control+C. Multiple Phase 5 workers can process independent opportunities; jobs within one opportunity are serialized.

## Optional workflow reference (already tested automatically)

The browser/HTTP tests have executed this workflow; routine manual testing is not required. For optional practice, use only fictional data. Leave AI budgets/rates at zero, provider **Mock**, website fetch off, and optional AI credentials unconfigured.

1. In **Leads & clients**, create `Fictional Studio`, email `prospect@example.com`, industry `Design`, location `Sydney`. Website can be blank; no URL does not mean the business lacks a website.
2. In **Sales team → Sender, GST and optional AI configuration**, set sender `owner@example.com`, provider **Mock**, GST **Not registered**, and save with all AI limits zero. These fictional sender details are not verified email authentication.
3. Create `Fictional one-page package`, category **one-page**, AUD `100.00`, **one-off**, scope `One fictional service page`, exclusions `Hosting, domain, publication and payments`. This is a test price, not a recommended commercial price.
4. Start a sales opportunity for the fictional lead, select that package, **Create local research**, **Local drafting**, and approve the lead for internal work. Mark it **fictional test workflow**.
5. Refresh the opportunity after the worker runs. Review the saved facts and select **Approve research and queue outreach**. The worker generates an actual local draft.
6. Review the draft, enter `prospect@example.com` and approve it. A correspondence record is created, but nothing is sent. Review the exact sender/recipient/subject/body, then explicitly queue **mock dispatch**. The worker records **Mock accepted**, not real delivery.
7. Optionally schedule a 1-hour **internal review**, then record `Fictional test: what does the package include?` as an owner-recorded reply. The original remains labelled owner-recorded, not provider-verified. The reply stops stale follow-up reviews. After classification, review the interpretation and prepare a local reply draft. Do not mistake generated text for an actual customer reply.
8. Enter fictional requirements and a source such as `Synthetic test fixture, not a real agreement`. Queue a local proposal. Review it and approve it; the worker creates an itemised AUD quote. One-off and recurring totals remain separate.
9. Approve the quote version and prepare correspondence. No real email is sent. For this fictional test only, record explicit fictional acceptance evidence, its source and the customer name, and confirm project creation. The app creates one project brief linked to that exact quote hash. It does not generate a website, invoice or payment.
10. Inspect history, original correspondence, quote versions and the Phase 6 project brief. Try **Agency Manager → Emergency pause** on another pending workflow, then resume or cancel it.

Mock dispatch accepts only explicitly fictional workflows and reserved test domains (`example.com`, `example.org`, `example.net`, or `.test`, `.invalid`, `.example`). It allows at most one attempt per recipient per UTC day and ten per owner/day. Do not use real business addresses. These protections are not marketing consent or provider permission.


## Worker and database troubleshooting

The app and worker now print the **absolute database path** and **database identity** at startup. Compare both, not merely whether a worker process exists. Relative `AGENCYOS_DB` values now resolve from the checkout directory, independent of the terminal working directory. No database is moved or searched automatically. If an older relative path referred to another location, select the intended **backup copy** by its full path.

Read-only diagnostics (does not run jobs or migrate a database):

```sh
python manage.py doctor --phase5 --database "$PWD/.development/agencyos-phase5.db"
```

Sales Team and Agency Manager also show recent matching worker heartbeats, pause state and per-phase queue counts under **Database and worker status**. A heartbeat within 60 seconds is evidence of a recent connection, not a guarantee that a process is alive now.

- **Sales Team opportunities** use `--phase5`. Open **Existing opportunities**, then **Agent tasks / research approval**, **Draft reviews**, **Correspondence** or **Quotes**. Create new is for new sales work; repeating an identical creation reopens the existing active opportunity without duplicating it.
- **Agency Manager research** uses `--phase4` on the **same selected Phase 5 database**. A Phase 5 worker deliberately does not drain this separate queue. If you use that older workflow, run `python manage.py worker --phase4 --database "$PWD/.development/agencyos-phase5.db" --watch` separately. The legacy Phase 3 queue still uses neither phase flag.
- **Queued / Attempts 0** means no matching worker has claimed the job. Check phase, exact path, recent heartbeat, pause, not-before time and whether another task holds the opportunity's lease. Approval-gated work needs review, not another worker. No automatic paid/external task execution is enabled by these diagnostics.
- **Sender missing** is a real preparation prerequisite, not lost research. The error links directly to sender settings, preserves the draft, and lets you return to its existing opportunity. Saving settings does not send email or establish SPF/DKIM/DMARC/provider permission.

Source evidence and prior records remain intact. New project briefs include acceptance evidence/source/provenance. Legacy schema-v1 briefs are enriched on read from their linked acceptance record without rewriting the stored brief or quote; inconsistent linkage is rejected.

## Automated validation

```sh
source .venv/bin/activate
python -m unittest discover -s tests -v
python tests/smoke_server.py
python tests/smoke_sales.py
python -m pip check
```

Optional maintainer browser runner: install `requirements-validation.txt` and Chromium, then run `python tests/browser_phase5.py --artifacts /tmp/agencyos-browser-evidence --chromium /path/to/chromium`. The completed validation used Playwright 1.64.0 and preinstalled Chromium 154, with external browser requests blocked. See the final report for evidence and exact commands; you do not need to run these tests yourself.

Tests use synthetic records, temporary databases and mocked external providers. Both smoke runners launch actual local servers and separate worker processes. `smoke_sales.py` also exercises concurrent workers, signed mock events, reply handoffs, proposals, quotes, acceptance and pause/restart. No external API call or customer contact is required. Python 3.13 was tested on Linux, not represented as a physical MacBook or visual-browser test.

## Controls and limitations

- No live email, invoice issuance, payment, website generation, publication or public deployment executor is added.
- All production AI transport calls require a one-use exact-request capability from an approved/budgeted Phase 5 job. Legacy direct AI routes are deliberately blocked; existing local drafting and historical AI records remain available.
- Optional AI requires current model/pricing configuration, positive owner-authorised limits and separate per-job approval. Do not activate paid calls under this release's development authorisation.
- Provider policy, consent/privacy, SPF/DKIM/DMARC and sender verification are not established by filling settings. Amazon SES is a candidate, not a connected/approved provider. No live activation switch exists.
- Acceptance records are **owner-attested evidence**, not independent customer identity verification. An editable legacy Accepted status does not create a project.
- Workers operate while running; 24/7 hosting, operational monitoring and automatic backup are future deployment work. Revenue is not guaranteed or reported as earned by a draft/quote.

Stop app and workers before copying the selected database to a secure backup outside Git. Preserve originals. Migrations add sales tables; trial older data only on a copy. Never run older versions against an upgraded copy.

Details: [PHASE5.md](PHASE5.md), [TEST_RESULTS.md](TEST_RESULTS.md). Historical instructions/results remain in [README_PHASE4.md](README_PHASE4.md), [TEST_RESULTS_PHASE4.md](TEST_RESULTS_PHASE4.md), and the retained Phase 3 documents.

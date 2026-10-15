# AgencyOS — Phase 4, milestones 1–3

Working local coordination, Australian licensed-data intake and evidence-backed website audits, built on Phase 3. The existing dashboard, CRM, financial tools, projects and earlier task history are preserved. This is a local single-owner development application, not a public deployment.

**No nationwide live discovery provider is approved or enabled.** The new discovery workflow searches owner-authorised CSV datasets locally. No real business data or results are seeded. Qualification/research uses explicit local rules, not pretend model responses. Audits perform actual HTTP checks when separately authorised; development tests mock those requests.

## MacBook installation: use a new folder

Install Python 3.13 from [python.org](https://www.python.org/downloads/macos/) if `python3.13 --version` is unavailable. macOS may offer command-line tools when Git is first used. Keep your previous AgencyOS folders/databases intact.

```sh
git clone --branch agencyos-phase4 --single-branch https://github.com/wombat9595-png/AgencyOS.git AgencyOS-Phase4
cd AgencyOS-Phase4
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
mkdir -p .development
export AGENCYOS_DB="$PWD/.development/agencyos-phase4.db"
export AGENCYOS_WEBSITE_FETCH=0
unset AGENCYOS_OSM_POLICY_FILE
python app.py
```

Alternatively download the `agencyos-phase4` ZIP from GitHub into a **new folder**, open Terminal there, and begin at the `python3.13 -m venv` command. No API key is needed. Do not point `AGENCYOS_DB` at an original database; it overrides the new default Phase 4 path.

The server prints its local address. Use its `/setup` path to create your development owner account, then sign in. It listens only on your computer. For an occupied port, set `export PORT=5001` before startup. The app generates a private in-memory session key; restarting signs you out. Persistent sessions require a securely supplied `AGENCYOS_SECRET_KEY`; `.env` files are not automatically loaded.

## Start the Phase 4 worker

In a second Terminal in your new Phase 4 folder:

```sh
source .venv/bin/activate
export AGENCYOS_DB="$PWD/.development/agencyos-phase4.db"
export AGENCYOS_WEBSITE_FETCH=0
unset AGENCYOS_OSM_POLICY_FILE
python manage.py worker --phase4 --watch
```

Both processes must select the same database. `--phase4` is important: omitting it selects the older Phase 3 queue, which can contain separately approved AI/discovery tasks. For one iteration omit `--watch`. Close the browser freely; keep the worker running and the Mac awake. No always-on system service is installed. Stop with Control+C.

## Use the milestones

1. Add a fictional lead, or import the synthetic CSV described in [PHASE4.md](PHASE4.md).
2. Open **Agency Manager**, assign qualification and optionally enable its local research handoff. Inspect inputs, score reasons, results and history.
3. Enable a local recurring qualification/research schedule. **Licensed discovery** also supports scheduled offline searches by state, city and industry, without external calls or automatic CRM imports.
4. Try **Emergency pause**. New claims and action forms stop; already dispatched requests may finish. Resume permits queued approved work again.
5. Prepare audits only for websites you are authorised to inspect. They remain awaiting approval with fetching disabled. Read [PHASE4.md](PHASE4.md) before enabling real requests.

The Phase 4 queue has a zero-dollar ceiling and no paid executor. Existing optional Phase 3 AI routes remain separate and outside this ledger; do not configure/run them under this milestone's no-charge authorisation. No email, invoice sender, payment, website builder, publication or deployment executor is added here. Existing manual financial statuses are not proof of customer agreement or bank payment.

## Tests

```sh
source .venv/bin/activate
python -m unittest discover -s tests -v
python tests/smoke_server.py
python -m pip check
```

Tests use fictional records, temporary databases and mocked external providers. The HTTP smoke test uses real local server/worker processes without external requests. Python 3.13 is validated on Linux, not represented as a MacBook/visual browser test. Results: [TEST_RESULTS.md](TEST_RESULTS.md).

## Preservation and further information

Stop app/workers before copying the selected database to a secure backup outside Git. Keep originals untouched. Test an upgrade only on a copy selected explicitly with `AGENCYOS_DB`; do not run an older app against an upgraded copy. Phase 4 migrations are additive and preserve existing records.

- [PHASE4.md](PHASE4.md): architecture, data format, controls, limits, costs and limitations.
- [PROVIDER_POLICIES.md](PROVIDER_POLICIES.md): preserved Phase 3 provider review status; no current online provider approval is claimed.
- [README_PHASE3.md](README_PHASE3.md): original Phase 3 documentation, retained for reference. Its database/worker commands are historical; use the instructions above for Phase 4.

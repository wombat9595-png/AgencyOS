# Where we're up to: Night Shift upgrade (branch claude/project-thread-mdpkej)

Built on top of `claude/office-agents-nayzje` (PR #7). Benji voted YES on all six upgrades in the "AgencyOS Night Shift" preview. Nothing here sends, spends or publishes. INSTALLED on Benji's Mac on 19 Oct 2026 (commit 521a72a; backup ~/AgencyOS-Backups/before-night-shift-20261019-104242). Runs at http://127.0.0.1:5050 in a Terminal window titled "AgencyOS".

## Done
- `playbook.py`: one shared playbook (voice, offer, packages, Spam Act opt-out, banned hype words, word limits, a page per niche, which story mock-up suits each trade). Every draft is checked against it.
- `night_shift.py` + `templates/night_shift.html` (`/night-shift`): once a day after 2 am Sydney, inside the existing worker, the agents search the next 2 search areas (OpenStreetMap), check websites, draft emails, count follow-ups and prepare monthly Profile Care posts. Catches up when the Mac wakes. "Run a shift now" button on Home.
- Home: new "Ready for you" queue (leads to approve, plan requests, profile posts, Gmail drafts) with approve/skip in one tap.
- `smart_writer.py`: optional Claude Haiku Writer. OFF by default; also blocked by the free-only lock (AGENCYOS_ZERO_COST=1 in local_run.py), needs ANTHROPIC_API_KEY and the `anthropic` package, and has a monthly cap (default A$5, max A$20). AI drafts must pass the playbook or the rules draft is used.
- `story_mockups.py` + `templates/stories/` + `static/motion/`: builders, landscapers and salons get the animated scroll-story demo personalised with their name, downloadable as one self-contained file (`/find-customers/<id>/story?download=1`).
- Profile Care add-on (A$49/month) in `client_plans.py`: 2 Google profile posts + 1 review request a month, drafted for approval.
- `site-check/`: public "free website check" page for Cloudflare Pages + Web3Forms. Not online; needs Benji's "put it online" and a free Web3Forms key.
- `deploy/night-shift/*.command`: optional scripts to make the Mac wake at 2:02 am (pmset). Not run.
- `tests/test_night_shift.py`: 9 tests.

- 19 Oct, Benji said "set up everything": Signature Website packages (A$2,400; founding A$1,900) are added automatically for an owner already set up; a private box on /night-shift saves the Anthropic key (0600 file next to the DB), and a key saved there is the Writer's only exception to the free-only lock; `anthropic` is added to requirements-local.lock, so the launcher installs it on next start; the shift keeps the Mac awake (caffeinate) while it runs and the wake script now wakes it at 2:02 am. Demo upload zip + steps are in the shared files (motion-kit/demos-upload.zip, PUT-DEMOS-ONLINE.md); not online. 330 tests pass.

## Waiting on Benji
- Add 1-2 search areas on /night-shift (none yet, so the shift has nowhere to search).
- Haiku: an Anthropic API key plus lifting the free-only lock, then tick the confirm box on /night-shift.
- "Put it online" for the website check page.

---

# Where we're up to: Office and the shared brain (branch claude/office-agents-nayzje)

Built on top of `claude/lead-engine-efqnp7` (PR #5, the copy installed on Benji's Mac). Nothing here sends, spends or publishes.

## Done
- `brain.py`: one shared, rule-based picture of the agency. Six sectors (Find customers, Outreach, Websites, Inbox, Money, Monthly clients), two agents each. Each agent gets a state from real local records: off (paused), asleep (tool not connected, e.g. Gmail), idle, working, waiting (needs Benji), cheering (money just landed). No AI model, no invented activity.
- `office.py` + `templates/office.html` + `static/office.js` + `static/office.css`: the Office page at `/office` (sidebar link under Home). Text-free animated SVG: six rooms around a central brain, figures walk, carry items and show icon bubbles; amber bell = waiting on Benji. Polls `/office/state` every 15 s. `?sample=1` plays a made-up busy day with a "Sample" chip; it also auto-plays the sample only when nothing at all is happening.
- CEO chat "What's everyone working on?" now appends `brain.describe()` (first_sale.py).
- Home dashboard: a full-width "Your agents right now" tile at the top embeds the live Office (same office.js), with an "N needs you" tag and an open-full-screen button.
- `tests/test_office.py`: 6 tests pass.

## Next (see the Word doc /mnt/project-files/plans/AgencyOS-office-and-brain-plan.docx)
1. Optional AI for the brain (Claude Haiku 5.5 API, ~A$2-3/month at expected use, needs Benji's OK and an API key; off by default, hard monthly cap).
2. Agent event log table so the Office replays real moves, not just current states.
3. Fold in Benji's dashboard-style video when he sends it.

## How to run / test
`python3 -m pytest -q tests/test_office.py` ; `python3 local_run.py --data-dir /tmp/x --no-browser --port 5077`, then open /office.

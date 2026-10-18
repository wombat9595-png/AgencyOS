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

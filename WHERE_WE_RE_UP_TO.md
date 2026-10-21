# Where we're up to: agent team and phone (branch claude/project-thread-mqtkmq)

Built on top of `claude/project-thread-4zj0lw` (PR #9, VIP upgrades), which is NOT yet installed on the Mac. Benji asked (21 Oct 2026) for a real org chart that pumps out drafts, agents he can teach, a Sydney-then-Australia lead sweep, Airtasker, and phone notifications plus AgencyOS on his phone. Nothing here sends, charges or publishes.

## Done
- `team.py` + `templates/team.html` (`/team`, sidebar "Team"): CEO, Chief of Staff, Sales Manager and six workers (Scout, Inspector, SEO Checker, Writer, Call Prepper, Designer), each with a written playbook and a live scorecard. Rules-based (A$0); Haiku used only for writing and the CEO's second opinion when switched on.
- CEO review (`team.ceo_review`, run at the end of every night shift): playbook check + Benji's "never use" words; AI drafts that fail are swapped for the rules draft; with Haiku on the CEO can ask the Writer for one rewrite. `prospects.ceo_status` = ready / held / redo; held and redo drafts stay out of the queue.
- Teaching: lessons per agent (`team_lessons`), every yes/edit/no stored (`team_feedback`, hooked into the approve action and a new `redo` action with a reason). The same no-reason 3 times becomes a standing rule ("too long" switches the rules Writer to a short first email; "not a fit" x3 for a trade stops drafting that trade). `team.coaching` feeds lessons, learned rules and Benji-edited approved emails (business name masked) into the Haiku brief.
- Chief of Staff (`team.plan`): squares per night (default 24), new drafts per day (default 25 minus drafts already waiting), and AI pacing (`smart_writer.paced_cents`: even share of the cap + 20% buffer). Haiku default cap raised to A$20 (approved by Benji).
- `sweep.py`: Greater Sydney (165 squares of 0.05°), then 19 other cities/regional centres (1,054 squares total). One Overpass query per square for all trades with no website tag; 2 s between squares; stops on a busy service and carries on next night.
- SEO Checker: `lead_engine.seo_notes` adds `seo` to the site check (no meta description, no h1, no tap-to-call, no LocalBusiness schema, thin title). Does not change scores.
- Phone: `/m` "Yes or no" page (phone layout, Yes / No-because chips), web app manifest + icons + no-cache service worker so it can go on the home screen; `team.notify` buzzes via ntfy (`pitch.ping` now takes a click URL): max 3 a day, 7 am to 9 pm, only when the pile grows, never includes business names. Private Tailscale address (`*.ts.net` only) saved on /team is added to TRUSTED_HOSTS (file `phone_host` in the private data dir).
- Airtasker: no scraping (their guidelines restrict "harvesting member information" and "lead generation related activities"). Quote helper on /team drafts a quote with no contact details.
- `tests/test_team.py`: 13 tests.

## Waiting on Benji
- Install (brings in PR #8 and #9 too) when he types the permission in the thread.
- ntfy app + "Turn on phone pings" on /studio. Optional: Tailscale account (his call) and `tailscale serve` for the phone address.
- Next idea: rename the Office robots to match the team.

---

# Where we're up to: VIP upgrades (branch claude/project-thread-4zj0lw)

Built on top of `claude/project-thread-mdpkej` (PR #8, commit c6f1b94, which is NOT yet installed on the Mac). Benji said "yes to everything" on the 18-item menu in the "Road to Client One" artifact (21 Oct 2026). Nothing here sends, charges or publishes.

## Done
- `phone.py` + `templates/calls.html` (`/calls`, sidebar "Calls"): daily call sheet (call-backs, interested, then grade A/B leads with a phone), 30 second opener from the real site problem, 8 objection answers, one-tap call logging (incl. call back on a date + note), the one-two after a missed call (voicemail script, text with STOP opt-out, "just tried you" email through the normal approve flow), Australian telemarketing hours banner, daily scoreboard + streak (also a Home tile), "What's working" by trade / phone vs email / subject line.
- Lead grades A/B/C (`phone.grade`) shown on Find customers and Call Mode.
- Subject-line testing: 3 first-email subjects rotate; `prospects.variant` is stored on approve; `lead_engine.best_subject` picks a winner once each has 15+ tries and most new leads get it.
- `getpaid.py` + `templates/get_paid.html` (`/get-paid`, sidebar "Get paid"): real invoices INV-0001…, 50% deposit / balance / monthly / other, GST on top only if registered, PDF (reportlab) with ABN, bank details (encrypted with the launcher's bank.secret via phase7_billing._fernet) and optional Stripe Payment Links (card, autopay). Mark paid after checking the bank; paid invoices count in Money in. No Stripe key is ever held.
- `pitch.py`: proposal page per lead (`/pitch/<id>/proposal`), 60 second video audit script (`/pitch/<id>/video`), booking link (added to first emails, proposals, homepage), reply detection (incoming Gmail from a lead stops follow-ups and pings the owner's phone via ntfy if he turned it on), Studio page (`/studio`), studio homepage + one niche page per night-shift search area, and the publish pack zip (homepage, niche pages, demos, `/p/<random>/` preview + proposal per good lead, `/c/<random>/` client pages; robots + noindex headers).
- `grow.py`: review request, testimonial ask (30 days after start), referral offer + referral tracking with free months owed, testimonials (only with the client's OK) shown on the homepage, private client page data.
- `tests/test_vip.py`: 10 tests.

## Waiting on Benji
- Install this on the Mac (after PR #8's update) when he says so.
- Type ABN, GST choice and bank details on /get-paid on the Mac (never in chat).
- Booking link, Google review link, ntfy topic, Stripe links: optional, all on /studio and /get-paid.
- "Put it online": upload the publish pack to Cloudflare Pages, then paste the address on /studio. Until then preview links don't show.

---

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

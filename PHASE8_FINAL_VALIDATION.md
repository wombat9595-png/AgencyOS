# Phase 8 final validation

Date: 2026-10-16 (Australia/Sydney)

## Implemented

- Unified `/operations` view for Phase 3/4/5/8 queue counts, worker/database heartbeats, Agent Center task status, recent failed/interrupted work, Phase 3 request usage and Phase 4/5 AI reservations.
- Phase 8 CLI worker (`manage.py worker --phase8 [--watch]`) that claims only enabled local lead-research tasks, performs saved-record analysis, and leaves AI tasks with their existing explicit approval path.
- Owner-scoped weekly local-time schedules with IANA time zones, selected weekdays, DST gap handling, durable schedule-run records, stopping, emergency-pause behavior and a 50-pending-task ceiling. If the worker was stopped, a schedule creates at most one catch-up run and advances to its next future occurrence.
- Durable daily local summaries, configured per owner/time zone, unique per local date, containing task/queue states and applicable request/reservation totals. Summaries are private and never emailed.
- Queue-pressure and disabled-handler events appear in Operations. Existing phase-specific retry/recovery/cancel behavior and spending controls remain in place.

## Test results

- `.venv/bin/python -m unittest discover -s tests`: **204 passed**, 0 failures (47.179 seconds).
- Phase 8 focused suite: **9 passed**, covering owner and queue view, time-zone validation, DST gaps, repeatable migrations, schedule deduplication, actual Phase 8 CLI worker execution/heartbeat, concurrent worker claims, emergency pause, AI-task isolation, queue-pressure ceiling and durable owner-scoped daily summaries.
- `.venv/bin/python tests/smoke_server.py`: pass; Operations page is included in live HTTP route checks.
- `.venv/bin/python tests/smoke_sales.py`: pass; existing two-worker Phase 5 workflow and emergency controls remain intact.
- `.venv/bin/python tests/browser_phase5.py --artifacts output/pdf`: pass in Chromium. Real UI login/navigation includes Operations; the end-to-end synthetic Phase 5/6 sales, website preview/revision/approval and pause/resume flow passed.
- Browser requests outside the local app were intercepted. No external site, email, payment, or AI service was contacted.
- `.venv/bin/python -m pip check`: no broken requirements.
- `git diff --check`: pass.

## Boundaries

Phase 8 schedules call only the zero-cost local handler using saved lead fields. They do not discover leads, fetch websites, invoke AI, contact anyone, issue invoices, take payments, or publish sites. Existing live email and publication actions remain unavailable. The Phase 8 worker uses the selected database and exposes a phase-specific heartbeat; `manage.py doctor --phase8` is read-only.

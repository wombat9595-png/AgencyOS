# Phase 8 — Agent orchestration and operations

Phase 8 connects the existing Phase 3–5 durable queues to a shared Operations view and adds a dedicated Phase 8 worker for safe local Agent Center work. It does not replace or merge the established queues: phase-specific workers and approval gates remain explicit.

## Operations view

Open **Operations** in the sidebar or visit `/operations`. It combines phase queue counts, recent worker heartbeats, Agent Center task states, recent failures/interruption messages, and today’s Phase 4/5 AI budget reservations. The dashboard keeps worker phase and database identity distinct. It links the emergency pause control to Agency Manager; the existing pause gates still block new Phase 3–5 and Phase 8 work.

## Phase 8 worker

Run with the same database path as the app:

```sh
AGENCYOS_DB="$PWD/.development/agencyos-phase5.db" python manage.py worker --phase8 --watch
```

Phase 8 claims only queued `lead-research` tasks in local mode. It uses the saved lead snapshot and moves successful results to **Awaiting review**. It does not claim AI tasks, contact leads, fetch websites, create invoices, take payments, or publish. Claims use SQLite write locks so concurrent workers do not run one task twice. The worker writes a matching database/phase heartbeat and shuts it down on exit.

## Local-time schedules

Operations supports up to 20 active weekly schedules per owner. Each schedule names an existing lead, local wall-clock time, IANA time zone and weekdays. Phase 8 calculates the next real occurrence across daylight-saving changes. Nonexistent spring-forward wall times are skipped. If an occurrence is missed while the worker is stopped, it queues at most one task and moves the schedule to its next future occurrence rather than flooding the queue. At 50 pending Agent Center tasks, that occurrence is skipped and the schedule advances.

Schedules create durable `agent_tasks` entries linked through `p8_schedule_runs`. They run only the zero-cost local saved-record handler. Stopping a schedule prevents future tasks; already queued tasks remain visible and cancellable through Agent Center. A running task can complete but needs a separate owner review.

## Daily summaries

An owner can select a local time and IANA time zone for a private daily summary. The Phase 8 worker stores one unique summary per owner and local date. It reports task/queue states and Phase 3 provider calls plus Phase 4/5 AI reservations. Reservations are ceilings, not billed amounts. It does not send an email and does not label workflow status as a business outcome.

## Controls and boundaries

- Existing Phase 3 provider throttles, Phase 4 zero-cost budget boundary, Phase 5 per-request approvals/budgets, and global emergency pause remain in place.
- The Phase 8 scheduler and worker are local-only and bounded; no additional paid adapter was added.
- Failures are visible for owner review. Existing queues retain their local retry/recovery rules and never automatically repeat uncertain paid or external actions.
- Queue state remains durable in `agent_tasks`, `p3_jobs`, `p4_jobs`, and `p5_jobs`; Phase 8 schedule/summary metadata is stored in additive `p8_*` tables.

Run `PHASE8_FINAL_VALIDATION.md` for test and worker evidence.

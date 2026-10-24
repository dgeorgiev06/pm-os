# Walkthrough: planning the next sprint

A realistic run of `pm/sprint-planning`, step by step: what you say, what the CoS does, which
agents run, and how state moves. Your side is three short messages.

## 1. You ask

> **You:** Plan sprint 22 for STK. Focus on router beta readiness.

The CoS can name the job, so it skips the router:
`pmos task new --mode pm/sprint-planning --verb plan --inputs '{"sprint": "2026-S22", "project": "STK", "goals_hint": "router beta readiness"}'`
→ **T-101**, `queued`. It delegates T-101 to a fresh Worker.

> **CoS:** On it. Sprint 22 planning is running (T-101). I'll bring you a ranking to approve first.

## 2. Worker run 1 — prioritize (stage A)

- Role `pm/roadmap-strategist`, top tier. Reads the five core principles plus `plan-to-capacity`
  and `explicit-trade-offs` from `pmos task show`.
- Reads the backlog and the last three sprints from Jira (read-only). Runs `capacity.py`:
  **21 committed points, 3 stretch**.
- Writes `ranking.md` with a score and rationale per item and a "deliberately deferred" list.
- Submits `status: blocked` — **gate 1**. Nothing has been planned or written yet.

## 3. Gate 1 — you approve the priorities

> **CoS:** Ranking for sprint 22: 1. Operator health routing, 2. Unstake via router, 3. Exposure
> report, 4. Rate limiting. Deferred: ETH adapter spike (Q1 roadmap). Approve, or tell me what to change?
>
> **You:** Approve.

The CoS logs it (`pmos decide`), re-queues T-101 with your answer as a note, and delegates again.

## 4. Worker run 2 — plan and roadmap diff (stage B)

- As `pm/sprint-planner` (mid): `plan.md` with three sprint goals and 21 committed points.
- As `pm/roadmap-strategist`: `roadmap-diff.md`, only the entries that change.
- Creates child **T-102** (`pm/jira-tickets`, approval none) and moves T-101 to `waiting`.

## 5. Worker run 3 — tickets (child T-102)

- As `pm/jira-curator` (small): drafts four tickets. `dedupe.py` flags one as a duplicate of
  STK-402, so it becomes an update.
- Returns dry-run actions with idempotency keys and preview lines.

## 6. Reviewer run 1 — T-102

Fresh context; scores the core principles plus `testable-requirements`. Passes → `done`. pmos sees
the last child finish and re-queues T-101 automatically.

## 7. Worker run 4 — assemble (stage C)

Combines the roadmap action with the four ticket actions; submits `needs_approval`.

## 8. Reviewer run 2 — T-101

Checklist includes `plan-to-capacity` and the gate-1 rubric line. Passes (4.5) → `awaiting_approval`.

## 9. Gate 2 — one approval for everything

> **CoS:** Sprint 22 is ready. Approve these 5 changes?
> · Roadmap: 1 change (router beta → in progress, exposure report → sprint 22)
> · CREATE Story · 8 pts · Route new stake away from degraded operators
> · CREATE Story · 8 pts · Unstake through router API
> · UPDATE STK-402 · 5 pts · Exposure report per operator
> · CREATE Task · 3 pts · Router API rate limiting
>
> **You:** Yes.

`pmos task approve T-101` records your approval with a hash of exactly what you approved; the CoS
delegates to the Operator.

## 10. Operator run — execute

The only agent with write tools; acts only on `approved` tasks. Checks each idempotency key, applies
the five actions, writes `applied.json`, moves T-101 to `done`.

> **CoS:** Done. Sprint 22 has 3 goals and 21 points; 3 tickets created, STK-402 updated, roadmap updated.

## Agents that ran

No new agent types were created: each step is a short-lived run of one of the four agents, started
from a task id.

| Agent | Runs | Role and tier | Can write? |
| --- | --- | --- | --- |
| CoS | 1, for the whole conversation | mid | No |
| Worker | 4 | strategist (top), planner (mid), curator (small) | No |
| Reviewer | 2 | mid | No |
| Operator | 1 | small | Yes, after approval |

- Your thread stayed free: the CoS replied within seconds each time.
- Only the ranking used the top tier; capacity math and dedupe ran as code.
- State lived in `pmos`, not in any agent: a crashed run is picked up by the next Worker from T-101.

## Variations

- **Through the router.** "Get the router beta launch-ready" goes to `pm/router`, which writes a
  plan (PRD, sprint planning, release notes), stops for your OK because sprint planning is high
  risk, then runs each as a child task.
- **Tracking the sprint** (durable runtime): see `examples/dbos/sprint_workflows.py` —
  `track_sprint` checks Jira daily in code, spends a model call only on new risks, and closes the
  sprint with a review that feeds actual velocity into the next plan.

---
name: pm-sprint-planning
description: Prioritize the next sprint, update the roadmap, plan the work and draft Jira tickets for a pm-os task whose envelope mode is pm/sprint-planning. Use when a Worker has been given such a task id.
---
# pm/sprint-planning — prioritize, plan, roadmap diff, tickets

Three stages across several deliveries of one task. `outputs/<id>/progress.json` holds
`{"stage": "A" | "B" | "C"}`; create it in stage A.

1. `[code: python scripts/pmos.py task show <id>]` at the start of every delivery; read
   `progress.json`, the history notes and any child tasks, then continue at your stage.

## Stage A — gather and prioritize

2. `[candidate-code]` Read the backlog with read-only Jira tools
   (`project = <project> AND status = Backlog ORDER BY rank`); save `outputs/<id>/backlog.json` as
   `[{key, summary, points, epic, labels}]`.
3. `[candidate-code]` Read velocity for the last 3 sprints and this sprint's availability; save
   `outputs/<id>/velocity.json` as `{"velocities": [..], "availability": 0.0-1.0}`.
4. `[code: python packs/pm/modes/sprint-planning/scripts/capacity.py outputs/<id>/velocity.json]` —
   save its JSON to `outputs/<id>/capacity.json`.
5. `[model]` As pm/roadmap-strategist (`python scripts/pmos.py role show pm/roadmap-strategist`), rank
   the backlog with `pm:domain/prioritization` into `outputs/<id>/ranking.md` (rank, key, score,
   rationale) and `ranking.json`.
6. `[code: python scripts/pmos.py task result <id> outputs/<id>/result.json]` — **gate 1**: set stage
   `"B"`, submit `status: "blocked"`, `artifacts: [ranking.md]` and
   `open_questions: ["Approve this ranking, or tell me what to change"]`.

## Stage B — plan and roadmap diff

7. `[model]` Read the PM's answer in the history notes. If they asked for changes, set stage `"A"`
   and redo step 5 with their notes.
8. `[model]` As pm/sprint-planner, write `outputs/<id>/plan.md` and `plan.json` with
   `pm:domain/sprint-planning`, within `capacity.json`'s `committed_points`.
9. `[code: python packs/pm/modes/sprint-planning/scripts/check_plan.py outputs/<id>/plan.json outputs/<id>/capacity.json]`
   — on `over capacity`, move items to stretch until it passes.
10. `[model]` As pm/roadmap-strategist, write `outputs/<id>/roadmap-diff.md`: only the entries that
    change, before → after, each tied to a ranked item.
11. `[code: python scripts/pmos.py task new --mode pm/jira-tickets --parent <id> --approval none --inputs '{"plan": "outputs/<id>/plan.json", "project": "<project>", "sprint": "<sprint>"}']`
    — its tickets roll up to this task's gate 2 and are reviewed with it.
12. `[code: python scripts/pmos.py task move <id> waiting]` after setting stage `"C"`.

## Stage C — hand off

13. `[model]` From `task show`, read only the child's summary and ticket preview, not its drafts.
14. `[code: python scripts/pmos.py task result <id> outputs/<id>/result.json]` — `status:
    "needs_approval"`; artifacts: ranking.md, plan.md, roadmap-diff.md, the child's preview; `outputs`:
    the `returns` paths plus the child's `ticket_actions`; one action
    `{"system": "roadmap", "op": "apply_diff", "idempotency_key": "<id>-roadmap", "payload": {"diff": "outputs/<id>/roadmap-diff.md"}, "preview": "Roadmap: <n> changes"}`.
    pmos appends the child's ticket actions; gate 2 approves both.

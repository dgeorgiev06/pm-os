---
name: pm-sprint-planning
description: Prioritize the next sprint, update the roadmap, plan the work and draft Jira tickets for a pm-os task whose envelope mode is pm/sprint-planning. Use when a Worker has been given such a task id.
---
# pm/sprint-planning — prioritize, plan, roadmap diff, tickets

Step tags: `[model]` = your judgment · `[code: …]` = run the script, don't do it by hand ·
`[candidate-code]` = done by you for now, on the list to become a script.

This mode runs in **three stages** across several deliveries of the same task. Track where you are
in `outputs/<id>/progress.json` (`{"stage": "A" | "B" | "C"}`); create it at stage A.
Start every delivery with `[code: python scripts/pmos.py task show <id>]` and read `progress.json`,
the task history notes and any child tasks it lists.

## Stage A — gather and prioritize (role: roadmap-strategist)

1. `[candidate-code]` Build the backlog query: `project = <project> AND status = Backlog ORDER BY rank`.
   Read it with read-only Jira tools; save to `outputs/<id>/backlog.json`
   (list of `{key, summary, points, epic, labels}`).
2. `[candidate-code]` Read velocity for the last 3 sprints and team availability for this sprint;
   save `outputs/<id>/velocity.json` as `{"velocities": [..], "availability": 0.0-1.0}`.
3. `[code: python packs/pm/modes/sprint-planning/scripts/capacity.py outputs/<id>/velocity.json]` →
   save its JSON output to `outputs/<id>/capacity.json`.
4. `[model]` As **pm/roadmap-strategist** (`python scripts/pmos.py role show pm/roadmap-strategist` prints its
   skills, principles and context), rank the backlog with the `pm:domain/prioritization` skill. Write `outputs/<id>/ranking.md` (table: rank, key, score,
   rationale) and `ranking.json`.
5. **Gate 1 — priorities.** Set stage to `"B"`, then submit a result with `status: "blocked"`,
   `artifacts: [ranking.md]`, and `open_questions: ["Approve this ranking, or tell me what to change"]`.
   The CoS asks the PM and re-queues this task with their answer in the history notes.

## Stage B — plan and roadmap diff

6. Read the PM's answer in the history notes. If they asked for changes, go back to step 4 with
   their notes and stay in stage A.
7. `[model]` As **pm/sprint-planner**, write `outputs/<id>/plan.md` and `plan.json`: 2–4 sprint goals,
   committed items within `capacity.json`'s `committed_points`, stretch items, risks with owners.
8. `[model]` As **pm/roadmap-strategist**, write `outputs/<id>/roadmap-diff.md`: only the roadmap
   entries that change, before → after, each tied to a ranked item.
9. Create the child task for tickets, then wait:
   `[code: python scripts/pmos.py task new --mode pm/jira-tickets --verb draft --parent <id> --approval none --inputs '{"plan": "outputs/<id>/plan.json", "project": "<project>", "sprint": "<sprint>"}']`
   Set stage to `"C"`, then `[code: python scripts/pmos.py task move <id> waiting]`.
   The child's actions execute only through this task's gate 2, never on their own.

## Stage C — assemble and hand off

10. `[code: python scripts/pmos.py task show <child id>]` → read the child's `result.json`.
11. `[model]` Self-check against acceptance and every principle and rubric line `task show` lists. Committed points must not exceed capacity.
12. Submit the result with `status: "needs_approval"` and:
    - `artifacts`: ranking.md, plan.md, roadmap-diff.md, and the child's ticket preview
    - `actions`: one roadmap action
      `{"system": "roadmap", "op": "apply_diff", "idempotency_key": "<id>-roadmap", "payload": {"diff": "outputs/<id>/roadmap-diff.md"}, "preview": "Roadmap: <n> changes"}`,
      followed by every action from the child's result, unchanged.
    Review and **gate 2** (one approval for roadmap + tickets) follow; the Operator executes.

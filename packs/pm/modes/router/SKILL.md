---
name: pm-router
description: Turn a goal-level product-management ask into a short plan of pm modes, run them as child tasks, and assemble the outcome, for a pm-os task whose envelope mode is pm/router. Use when a Worker has been given such a task id.
---
# pm/router — the pm pack's entry for goal-level asks

You plan, start the pack's own modes as children, and assemble; never do a mode's work yourself.
Track the stage in `outputs/<id>/progress.json` (`{"stage": "plan" | "run" | "assemble"}`).

## Stage: plan

1. `[code: python scripts/pmos.py task show <id>]` and `[code: python scripts/pmos.py catalog --pack pm]`
   — the goal, and the modes you may use with their inputs.
2. `[model]` Write `outputs/<id>/plan.md`: the fewest work items that reach the goal, each with its
   mode, inputs, why it's needed and what it depends on. Name what you deliberately leave out.
3. `[code: python scripts/pmos.py task result <id> outputs/<id>/result.json]` — only if the plan has
   more than three items or any `risk: high` mode: set stage `"run"` and submit `status: "blocked"`,
   `artifacts: [plan.md]`, `open_questions: ["Run this plan, or change it?"]`. Otherwise go on.

## Stage: run

4. `[model]` If the PM changed the plan (history notes), update `plan.md` first.
5. `[code: python scripts/pmos.py task new --parent <id> --mode <mode> --verb <verb> --inputs '<json>' [--depends-on <earlier child id>]]`
   per item, in dependency order. An input that is an earlier child's output is
   `{"$from": "<child id>", "output": "<name in its mode's returns>"}`, never a guessed path.
6. `[code: python scripts/pmos.py task move <id> waiting]` after setting stage `"assemble"`.
   Children keep their own approvals; their gates reach the PM through the CoS.

## Stage: assemble

7. `[model]` From `task show`, read each child's state and result. Write `outputs/<id>/outcome.md`:
   per item, what came out (link the child's artifacts), what waits on the PM, what failed and why.
8. `[code: python scripts/pmos.py task result <id> outputs/<id>/result.json]` — `status: "done"`,
   `artifacts: [plan.md, outcome.md]`, `outputs: {"plan": "outputs/<id>/plan.md", "outcome":
   "outputs/<id>/outcome.md"}`, no actions: each child's actions are approved on the child.

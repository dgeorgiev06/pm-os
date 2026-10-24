---
name: pm-router
description: Turn a goal-level product-management ask into a short plan of pm modes, run them as child tasks, and assemble the outcome, for a pm-os task whose envelope mode is pm/router. Use when a Worker has been given such a task id.
---
# pm/router — the pm pack's entry for goal-level asks

The CoS sends work here only when the ask is a goal ("get the router beta launch-ready"), not a
single job it can name ("draft a PRD for X" goes straight to `pm/prd`). You plan, delegate to the
pack's own modes, and assemble. You never do a mode's work yourself.

Like other multi-stage modes, track your stage in `outputs/<id>/progress.json` (`{"stage": "plan" | "run" | "assemble"}`).

## Stage: plan

1. `[code: python scripts/pmos.py task show <id>]` and `[code: python scripts/pmos.py catalog --pack pm]`
   — the goal, and the modes you may use with what each accepts.
2. `[model]` Write `outputs/<id>/plan.md`: the fewest work items that achieve the goal, each with
   the mode, its inputs, why it's needed, and what it depends on. Name what you're deliberately not doing.
3. If the plan has more than three items or any `risk: high` mode, stop for the PM first:
   set stage to `"run"` and submit `status: "blocked"` with `artifacts: [plan.md]` and
   `open_questions: ["Run this plan, or change it?"]`. Otherwise go straight to Stage: run.

## Stage: run

4. If the PM changed the plan (see history notes), update `plan.md` first.
5. Create one child task per item, in dependency order, passing dependencies explicitly:
   `[code: python scripts/pmos.py task new --parent <id> --mode <mode> --verb <verb> --inputs '<json>' [--depends-on <earlier child id>]]`
   When an input is an earlier child's output, pass `{"$from": "<earlier child id>", "output": "<name from its mode's returns>"}`
   as its value instead of guessing a path: pmos checks the output exists, adds the dependency, and
   resolves the value when the child starts.
   Children keep their own approval rules; their gates reach the PM through the CoS as usual.
6. Set stage to `"assemble"`, then `[code: python scripts/pmos.py task move <id> waiting]`.

## Stage: assemble

7. `[code: python scripts/pmos.py task show <id>]` lists every child, its state and result.
8. `[model]` Write `outputs/<id>/outcome.md`: per item, what came out (link the child's artifacts),
   what is still waiting on the PM, and anything that failed with its reason.
9. Submit `status: "done"` with `artifacts: [plan.md, outcome.md]`,
   `outputs: {"plan": "outputs/<id>/plan.md", "outcome": "outputs/<id>/outcome.md"}` and no actions: every
   action belongs to the child that proposed it and is approved there.

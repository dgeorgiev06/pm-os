# Proposal: `pm/todo-plan` with delegation

Status: **superseded.** Todos were built into the `cos` pack instead (`cos/todos` and
`packs/cos/scripts/todos.py`), with delegation only when the PM directs it; see
`../routing-and-delegation.md`. This proposal is kept as the worked example of what `forge/new-mode`
creates. The early name-and-contract gate for forge is still open.

## The ask

> "Add a mode to pm that manages my todo list for the next few days."

## What forge would create

```
outputs/<task>/
  design.md                      job, contract, role, principles, steps, eval
  result.json                    one repo.sync_pack action listing the files
  staged/pm/                     a copy of the pm pack, plus:
    pack.yaml                    new mode exported; version bumped one minor
    roles.yaml                   + day-planner (no existing role fits)
    modes/todo-plan/
      mode.yaml
      SKILL.md
      evals/golden-01.json
      scripts/plan_days.py
```

## The contract

```yaml
name: pm/todo-plan
version: 0.1.0
contract: task@1
summary: Plan the next few days from the todo list and calendar; add, close, reschedule and delegate todos
verbs: [plan]
accepts:
  days: number?        # default 5
  add: list?           # new todos in plain words: ["review STK PRD by Tue, 1h"]
  done: list?          # ids finished since the last plan
  focus: string?       # e.g. "router beta first"
returns:
  plan: doc_ref
  todo_diff: diff_ref
  delegations: list
default_role: day-planner
grants: { todos: draft, calendar: read }
approval: before_execute
risk: low
principles: [plan-to-capacity]
rubric:
  - Nothing due in the window is dropped silently; overflow is listed
  - No day is planned beyond its free hours
  - Only todos that match an exported mode with clear inputs are proposed for delegation
evals: evals/
```

## Steps

1. `[code]` `pmos task show <id>`.
2. `[code]` Read `context/todos.yaml`, plus the status board's "Needs the PM" items as short todos.
3. `[candidate-code]` Read calendar busy blocks → free hours per day.
4. `[model]` Turn `add` entries into `{title, estimate_h, due, priority}`; close `done` ids; for each
   todo, propose `owner: agent` with a mode and inputs if one fits the catalog, else keep it yours.
5. `[code]` `plan_days.py`: due date first, then priority, filled to free hours; delegated todos use
   only their `review_h`; the rest is overflow.
6. `[model]` `plan.md`: one list per day, what didn't fit and why, the proposed delegations.
7. `[code]` Submit `needs_approval` with a `todos.apply_diff` action and the delegation list.

On your yes, the Operator applies the todo diff and the CoS creates one `pmos` task per approved
delegation; each todo records its task id.

## A delegated todo

```yaml
- id: td-12
  title: Draft release notes for S22
  owner: agent            # me | agent
  mode: pm/release-notes
  inputs: { sprint: 2026-S22, project: STK }
  task: T-131             # set once delegated
  due: 2026-10-28
  review_h: 0.25          # your time, not the agent's
```

## Changes to the framework

- `pmos task new --todo <id>` to link a task to the todo it came from, shown on the status board.
- `forge/new-mode` makes `name` optional and proposes the name and contract at an early gate, so
  you confirm the two things that are expensive to change later before the work is done.
- Installing it widens `pm`'s grants (`todos: draft`, `calendar: read`), so it needs
  `pmos pack add packs/pm --upgrade --approve-grants`.

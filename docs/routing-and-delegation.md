# Routing and delegation

## Who decides which mode handles the work

A model decides, `pmos` enforces the rules, and you have the final say. Who decides depends on
where the work comes from.

1. **You ask the CoS directly.** The CoS decides, following its manual: a concrete job it can name
   goes straight to that mode; a goal goes to the relevant pack's router, which then picks among
   its own modes; ties between packs go local → org → third-party, then to you. It chooses from
   the catalog (each mode's one-line `summary` and `accepts`). `pmos` then checks the choice: the
   mode must be exported, and the inputs must match `accepts`.
2. **Delegating todos.** The `pm/todo-plan` Worker proposes a mode per todo; you approve the list
   before any task exists. A todo with no clear match stays yours.
3. **Inside a composite mode** (sprint planning creating a ticket task, the router running a plan),
   the mode's own steps decide, limited to the modes listed in its `calls`, which `pmos` enforces.

What keeps it honest: ambiguous cases go to you as a question, not a guess; misroutes show up in
traces (blocked on inputs, failed review, you redirecting) and the improvement loop sharpens the
summary that caused them. If routing needs to be more predictable, modes can list a few example
asks in `mode.yaml` for the CoS to match against.

## Who names a new mode

`name` is an input to `forge/new-mode`, so whoever creates the envelope picks it: you, or the CoS
from your words. Constraints: lowercase and hyphens, the pack prefix is forced, `forge.py` refuses
duplicates, and the forge Worker stops if an existing mode already does the job. Your final say is
the approval preview ("Add mode `pm/todo-plan` to pack pm"). Once installed, a name is part of the
contract (envelopes, `calls`, the router refer to it), so renaming later is a breaking change.
Planned improvement: forge proposes the name and contract at an early gate (see the proposal).

## Todos and tasks

Built into the `cos` pack. Two different things, linked:

- **Todos** are your list: what has to get done, by when. They live in `context/todos.yaml`
  (personal, not committed), managed by `packs/cos/scripts/todos.py`.
- **Tasks** are `pmos` work orders for agents.

### Managing todos

| You say | What happens |
| --- | --- |
| "Add 'prep demo' due Wednesday, 2h" · "done td-3" · "move td-4 to Friday" | The CoS runs `todos.py` directly. Your words are the approval; no agent runs. |
| "What's on my plate this week?" | The CoS runs `todos.py sync` and `todos.py plan`, and includes anything on the status board that's waiting on you. |
| "Plan my week; Thursday is all meetings; add the demo prep and push the API reading" | The `cos/todos` mode plans against your free hours and proposes a diff; you approve; the Operator applies it. |

`todos.py plan` fits open todos into free hours (6 per weekday by default, or what you give it), due
date first, then priority, and lists what doesn't fit instead of dropping it.

### Delegating a todo — only when you direct it

> **You:** Delegate td-12 to pm/release-notes. Focus on what custodians will notice; keep it to a page.

1. The CoS uses the mode you named, or picks one from the catalog and asks if more than one fits.
2. It fills the mode's inputs from the todo and your words, and asks if a required input is missing.
3. `pmos task new … --origin cos:td-12 --instructions "<your words, verbatim>"` creates the task;
   `todos.py link` marks the todo delegated.
4. The Worker sees your instructions at the top of `task show` and follows them; the Reviewer's
   checklist gains a line checking them. They never override a principle or an approval gate.
5. While the result waits for your approval, the todo shows **WAITING ON YOU** and costs only
   your review time in the plan. When the task finishes, `todos.py sync` closes the todo; if it
   fails, the todo comes back to you.

The CoS and `cos/todos` may *suggest* delegating ("td-3 could go to pm/release-notes if you say
so"); neither delegates unasked. That rule is the principle `cos:delegate-only-when-directed`.

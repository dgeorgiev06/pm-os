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

Two different things, linked:

- **Todos** are your list: what has to get done, by when. Your todo list is a system of record.
- **Tasks** are `pmos` work orders for agents.

How a todo is delegated:

1. **Classify.** `pm/todo-plan` checks each todo against the catalog. "Draft release notes for
   S22" maps to `pm/release-notes`; "call the custodian" maps to nothing and stays yours.
2. **Propose, don't act.** The plan lists the delegations next to your days; you approve them with
   everything else.
3. **The CoS creates the tasks** on your yes (`pmos task new` per todo) and each todo records its
   task id. Nothing starts before you approve.
4. **Only your review time is planned.** A delegated todo spends your hours on reviewing the
   result, not doing the work.

It also runs the other way: anything waiting on you on the status board (an approval gate, a
blocked question) comes back into your plan as a short todo, so agent work and your own work share
one list. A delegated todo shows its task's state live; when the task finishes, the next plan
proposes closing the todo. `pmos` itself never edits your todo list, because only approved actions
change a system of record.

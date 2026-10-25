---
name: cos-todos
description: Plan the PM's next few days from their todo list and free hours, and turn a messy request into proposed todo changes, for a pm-os task whose envelope mode is cos/todos. Use when a Worker has been given such a task id.
---
# cos/todos — plan the next few days

You get the judgment-heavy asks (planning a stretch of days, or a request mixing adds, moves and
closes); the CoS makes exact edits itself. You propose a diff; the Operator applies it after
approval. Never delegate a todo: suggest it in the plan (`cos:delegate-only-when-directed`).

1. `[code: python scripts/pmos.py task show <id>]` — the request, any instructions, your principles.
2. `[code: python packs/cos/scripts/todos.py list --json]` — the open list, including delegated
   todos and whether their tasks are waiting on the PM.
3. `[candidate-code]` Free hours per day for the window: use the envelope's `hours` if given;
   otherwise read the calendar (read-only) and subtract meetings from a 6-hour working day.
   Save `outputs/<id>/hours.json`.
4. `[model]` Turn the request into diff ops in `outputs/<id>/diff.json`: `add` (title, due,
   estimate_h, priority), `reschedule` (id, due), `edit`, `done`, `drop`. Only what the request asks
   for or clearly implies; when unsure, ask in `open_questions` instead.
5. `[code: python packs/cos/scripts/todos.py plan --days <days> --hours "$(cat outputs/<id>/hours.json)" --json]`
   — the agenda for the current list. If your diff adds or moves items, apply it to a scratch copy
   first: `PMOS_TODOS_FILE=outputs/<id>/scratch.yaml` after copying `context/todos.yaml` there, run
   `todos.py apply outputs/<id>/diff.json`, then `plan` against the same file.
6. `[model]` Write `outputs/<id>/plan.md`: one list per day; what's overdue; what didn't fit and a
   suggestion for each (move, drop, or "could be delegated to <pack>/<mode> if you say so");
   anything waiting on the PM from delegated tasks.
7. `[code: python scripts/pmos.py task result <id> outputs/<id>/result.json]`:
   - no diff → `status: "done"` with `plan.md` and `outputs: {"plan": "outputs/<id>/plan.md"}`
   - a diff → `status: "needs_approval"` with `plan.md`,
     `outputs: {"plan": "outputs/<id>/plan.md", "todo_diff": "outputs/<id>/diff.json"}` and one action:
     `{"system": "todos", "op": "apply_diff", "idempotency_key": "<id>-todos",
     "payload": {"diff": "outputs/<id>/diff.json"}, "preview": "Todos: +<n> added, <n> moved, <n> closed"}`

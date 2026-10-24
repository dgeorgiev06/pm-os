---
name: pm-release-notes
description: Draft release notes from the Jira tickets closed in a sprint, for customers or internal teams, for a pm-os task whose envelope mode is pm/release-notes. Use when a Worker has been given such a task id.
---
# pm/release-notes — release notes from a closed sprint

## Inputs (from the envelope)

`sprint` and `project` (required) · `audience`: `customers` (default) or `internal`.

## Steps

1. `[code: python scripts/pmos.py task show <id>]` — load the envelope, role (pm/communicator),
   principles and any revise notes. If revising, start from `outputs/<id>/notes.md`.
2. `[candidate-code]` Read the tickets closed in the sprint with read-only Jira tools
   (`project = <project> AND sprint = "<sprint>" AND status = Done`). Save `outputs/<id>/closed.json`
   as a list of `{key, summary, type, labels, description}`.
3. `[code: python packs/pm/modes/release-notes/scripts/group_tickets.py outputs/<id>/closed.json --audience <audience>]`
   — save its JSON output to `outputs/<id>/sections.json`. It sorts tickets into new features,
   improvements, fixes and internal work, and drops internal work for customer notes.
4. `[model]` Write `outputs/<id>/notes.md` from `sections.json`: a one-paragraph lead on what changed
   for the reader, then one section per non-empty group. One line per item in the reader's terms,
   ending with the ticket key. For customers, describe only behavior the ticket itself states.
5. `[model]` Self-check against the envelope's `acceptance` and every principle and rubric line
   `task show` lists.
6. `[code: python scripts/pmos.py task result <id> outputs/<id>/result.json]` with `status: "done"`,
   `artifacts: [{"kind": "doc", "ref": "outputs/<id>/notes.md"}]`, and `actions: []` unless the
   envelope asks to publish (then one `docs.publish` action with a preview line).

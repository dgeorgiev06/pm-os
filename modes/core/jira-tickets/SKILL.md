---
name: core-jira-tickets
description: Draft Jira tickets from a sprint plan as dry-run actions, deduplicated against existing tickets, for a pm-os task whose envelope mode is core/jira-tickets. Use when a Worker has been given such a task id.
---
# core/jira-tickets — draft tickets as dry-run actions

Step tags: `[model]` = your judgment · `[code: …]` = run the script, don't do it by hand ·
`[candidate-code]` = done by you for now, on the list to become a script.

You never create tickets. You produce actions; the Operator executes them after approval.

## Steps

1. `[code: python scripts/pmos.py task show <id>]` — load the envelope and role (jira-curator).
2. `[candidate-code]` Read open tickets in the project with read-only Jira tools; save
   `outputs/<id>/existing.json` as a list of `{key, summary, status}`.
3. `[model]` From the plan, draft `outputs/<id>/drafts.json`: a list of
   `{summary, type, description, acceptance_criteria: [..], points, epic, labels}` following
   `domain/jira-conventions`. One ticket per committed or stretch item that has no ticket yet.
4. `[code: python modes/core/jira-tickets/scripts/dedupe.py outputs/<id>/drafts.json outputs/<id>/existing.json]`
   — prints likely duplicates. For each: drop the draft, or turn it into an `update_issue` on the
   existing key if the plan changes it.
5. `[candidate-code]` Map each draft to a Jira payload (project, issuetype, summary, description with
   acceptance criteria, story points field, epic link, labels, sprint). Add the label
   `pmos-<idempotency_key>` so the Operator can detect repeats.
6. `[model]` Write `outputs/<id>/preview.md`: one line per action (`CREATE Story · 5 pts · <summary>`).
7. `[code: python scripts/pmos.py task result <id> outputs/<id>/result.json]` with `status: "done"`,
   `artifacts: [preview.md]`, and one action per ticket:
   `{"system": "jira", "op": "create_issue", "idempotency_key": "<id>-<n>", "payload": {...}, "preview": "<the preview line>"}`.

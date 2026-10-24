---
name: infra-envelope-io
description: How to read a pm-os task envelope and submit a result through scripts/pmos.py. Use in every pm-os task, whatever the mode.
---
# Envelope I/O

All state changes go through `python scripts/pmos.py`. Never edit files under `state/` by hand.

| Do | Command |
| --- | --- |
| See the task, mode, role, notes, children | `python scripts/pmos.py task show <id>` |
| Start work | `python scripts/pmos.py task move <id> running` |
| Wait for child tasks | `python scripts/pmos.py task move <id> waiting` |
| Create a child task | `python scripts/pmos.py task new --parent <id> --mode <m> --verb <v> --inputs '<json>'` |
| Submit a result | `python scripts/pmos.py task result <id> outputs/<id>/result.json` |

## Result shape (contracts/result.schema.json)

```json
{
  "task_id": "T-20261024-001",
  "status": "done | needs_approval | blocked | failed",
  "summary": "Under ~80 words. Leads with the outcome. The CoS forwards this verbatim.",
  "artifacts": [{ "kind": "doc", "ref": "outputs/T-20261024-001/prd.md", "title": "..." }],
  "actions": [],
  "self_check": [{ "criterion": "has success metrics", "met": true }],
  "open_questions": []
}
```

`task result` validates against the schema and rejects anything malformed; fix and resubmit.
`blocked` needs at least one `open_questions` entry. Don't fill in `review`; that's the Reviewer's.

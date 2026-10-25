---
name: cos-notify
description: "Notify an internal or external audience from a checked template, and propose one comms.send per recipient, for a pm-os task whose envelope mode is cos/notify. Use when a Worker has been given such a task id."
---
# cos/notify — one audience, checked, then approved

Inputs: `draft` (a draft.json path) · `audience` (`internal` or `external`) · `channels` (optional) · `send_at` (optional).

1. `[code: python scripts/pmos.py task show <id>]` — the envelope, your role and principles, and the draft path.
2. `[model]` Read the draft. Keep the entries for `audience`. An entry with no template uses the generic one for its channel, so it needs `channel` and `audience`. Fill only the fields the draft gives; never add a recipient.
3. `[code: python packs/cos/modes/notify/scripts/build_actions.py --check <draft>]` — each problem is named with its entry and field. Fix the draft until it prints `ok`. A refusal about internal-only text means the external text must be rewritten, not that the check is wrong.
4. `[code: python packs/cos/modes/notify/scripts/build_actions.py build <draft> --audience <audience> --task <id> --out outputs/<id> [--channels <names>] [--send-at <when>]]` — writes `messages.json` and `actions.json`.
5. `[code: python scripts/pmos.py task result <id> outputs/<id>/result.json]` — `outputs: {"messages": "outputs/<id>/messages.json"}`, the messages file as an artifact, and `actions` set to the contents of `actions.json`. Status `needs_approval`, or `done` when your envelope has a `parent`: the parent holds the approval.

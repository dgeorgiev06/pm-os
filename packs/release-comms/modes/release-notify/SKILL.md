---
name: release-comms-release-notify
description: "Draft a release's customer email and internal note from its release notes, then one cos/notify child per audience, for a pm-os task whose envelope mode is release-comms/release-notify. Use when a Worker has been given such a task id."
---
# release-comms/release-notify — one approval for a release's messages

Inputs: `release_notes` (the pm/release-notes output) · `audiences` (default `internal` and `external`).

1. `[code: python scripts/pmos.py task show <id>]` — the envelope, role, skills, and any child results.
2. `[model]` Read `release_notes`. Find the version and the ship date. If there is no ship date, go to step 7 and ask for it; never invent one.
3. `[model]` Write `outputs/<id>/draft.json`: one entry per audience, using `packs/release-comms/modes/release-notify/templates/external-email.md` and `internal-slack.md`. Copy the ship date exactly. Apply the customer-impact skill to the external changes; the internal note carries the known risks and support notes.
4. `[code: python packs/release-comms/modes/release-notify/scripts/check_draft.py outputs/<id>/draft.json]` — fix until it passes.
5. `[code: python scripts/pmos.py task new --parent <id> --mode cos/notify@^0.1 --verb draft --approval none --risk high --inputs '{"draft": "outputs/<id>/draft.json", "audience": "external"}']`, then the same for `internal` at `--risk medium`. Then `[code: python scripts/pmos.py task move <id> waiting]`.
6. When the children finish, `[code: python packs/cos/modes/notify/scripts/build_actions.py merge outputs/<id>/messages.json outputs/<external child>/messages.json outputs/<internal child>/messages.json]`, then submit with `draft` and `messages` as outputs, status `needs_approval`, and no actions of your own (pmos merges the children's).
7. Blocked: `[code: python scripts/pmos.py task result <id> outputs/<id>/result.json]` with status `blocked` and one open question, "What is the ship date for <version>?", and no draft.

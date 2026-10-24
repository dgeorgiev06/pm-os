---
name: forge-new-mode
description: Design a new pm-os mode for an installed pack, stage it, lint it, run a dry-run admission, and propose it for approval, for a pm-os task whose envelope mode is forge/new-mode. Use when a Worker has been given such a task id.
---
# forge/new-mode — add a mode to a pack

Build only under `outputs/<id>/staged/`; nothing reaches `packs/` before approval. Conventions:
`forge:authoring`. Below, "nested" means the envelope sets `into` (a forge/new-pack child).

1. `[code: python scripts/pmos.py task show <id>]` — the request, your role and principles.
2. `[code: python scripts/pmos.py catalog]` and `[code: python scripts/pmos.py catalog --pack <pack>]`
   — if an installed mode already does this job, submit `status: "blocked"` asking whether to extend
   it instead.
3. `[model]` Write `outputs/<id>/design.md`, contract and cases first: the one job; `accepts`,
   `returns`, approval; the role (an existing one, or the one new role it needs); cited principles;
   modes it calls; the tagged steps; the golden case's expectations, a failure path, a conformance
   case per script.
4. `[code: python packs/forge/scripts/forge.py stage-mode --task <id> --pack <pack> --name <name> --summary "<one line>" [--role <role>] [--into <into>] [--script <name> ...] [--router]]`
   — the skeleton with its eval cases; it exports the mode and, unless nested, bumps the pack's minor
   version.
5. `[model]` Replace every `TODO:` marker in the staged files with the design. Add a role only if
   none fits; fixtures go in the pack's `evals/fixtures/`.
6. `[code: python packs/forge/scripts/forge.py lint outputs/<id>/staged/<pack> --target packs/<pack>]`
   — markers, names, coverage and `pmos lint`; fix until PASS.
7. `[code: python scripts/pmos.py pack add outputs/<id>/staged/<pack> --upgrade --dry-run]` — unless
   nested; fix until it passes, and note any grants it lists as new or wider.
8. `[code: python packs/forge/scripts/forge.py changes outputs/<id>/staged/<pack> --target packs/<pack>]`
   — the file list for the action.
9. `[model]` Write `outputs/<id>/result.json`. Nested: `status: "done"`, `outputs: {"staged":
   "<into>"}`, no action. Otherwise: `status: "needs_approval"`, `outputs: {"staged":
   "outputs/<id>/staged/<pack>"}`, artifacts `design.md` and the staged `mode.yaml` and `SKILL.md`, and
   a summary with the PM's install command, `python scripts/pmos.py pack add packs/<pack> --upgrade`
   (plus `--approve-grants` if grants widened).
10. `[code: python scripts/pmos.py task result <id> outputs/<id>/result.json]` — unless nested, with one
    `repo.sync_pack` action: `idempotency_key: "<id>-sync"`, `payload: {"staged": …, "target":
    "packs/<pack>", "files": <step 8>}`, `preview: "Add mode <pack>/<name> to pack <pack> (<n> files,
    version <v>)"`.

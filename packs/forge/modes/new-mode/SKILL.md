---
name: forge-new-mode
description: Design a new pm-os mode for an installed pack, stage it, lint it, run a dry-run admission, and propose it for approval, for a pm-os task whose envelope mode is forge/new-mode. Use when a Worker has been given such a task id.
---
# forge/new-mode — add a mode to a pack

You build in the staging area only: `outputs/<id>/staged/`. Nothing reaches `packs/` until the PM
approves and the Operator applies it. Follow the `forge:authoring` skill for every convention.

Step tags: `[model]` = your judgment · `[code: …]` = run the command.

## Steps

1. `[code: python scripts/pmos.py task show <id>]` — the request, your role and principles.
2. `[code: python scripts/pmos.py catalog]` and `[code: python scripts/pmos.py catalog --pack <pack>]`
   — check that no installed mode already does this job (`forge:smallest-unit`). If one does,
   submit `status: "blocked"` and ask whether to extend that mode instead.
3. `[model]` Design, in `outputs/<id>/design.md`: the mode's one job; `accepts` and `returns`; the
   approval rule; which existing role runs it (or the one new role it needs); which principles it
   cites; any modes it calls; the steps, each tagged `[model]`, `[code]` or `[candidate-code]`; and
   the golden task's expectations. Write the contract and the golden task first (`forge:contract-first`).
4. Stage the skeleton:
   `[code: python packs/forge/scripts/forge.py stage-mode --task <id> --pack <pack> --name <name> --summary "<one line>" [--role <role>] [--into <into>]]`
   This copies the pack to staging (unless `into` is set), adds the mode, exports it, and bumps the
   pack's minor version.
5. `[model]` Replace every `TODO` in the staged `mode.yaml`, `SKILL.md` and `evals/golden-01.json`
   with the design. Add a role to the staged `roles.yaml` only if no existing role fits. Add scripts
   for `[code]` steps under the mode's `scripts/`.
6. `[code: python packs/forge/scripts/forge.py lint outputs/<id>/staged/<pack> --target packs/<pack>]` — fix until PASS.
7. Unless `into` is set (then the parent forge/new-pack checks the whole pack):
   `[code: python scripts/pmos.py pack add outputs/<id>/staged/<pack> --upgrade --dry-run]` — fix until
   it passes admission. Note any grants it lists as new or wider.
8. `[code: python packs/forge/scripts/forge.py changes outputs/<id>/staged/<pack> --target packs/<pack>]`
   — the file list for the action.
9. Submit the result:
   - `status: "needs_approval"` (or `"done"` when `into` is set: the parent proposes the whole pack)
   - `artifacts`: `design.md`, and the staged `mode.yaml` and `SKILL.md`
   - `outputs: {"staged": "outputs/<id>/staged/<pack>"}` (or the `into` directory when it is set)
   - one action: `{"system": "repo", "op": "sync_pack", "idempotency_key": "<id>-sync",
     "payload": {"staged": "outputs/<id>/staged/<pack>", "target": "packs/<pack>", "files": [<from step 8>]},
     "preview": "Add mode <pack>/<name> to pack <pack> (<n> files, version <new version>)"}` — omit when `into` is set.
   - In `summary`, say that after the Operator applies it the PM runs
     `python scripts/pmos.py pack add packs/<pack> --upgrade` (plus `--approve-grants` if step 7 listed
     new or wider grants). Installing is the PM's step, never an agent's.

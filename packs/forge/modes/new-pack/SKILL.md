---
name: forge-new-pack
description: Design a new pm-os pack with its roles, principles and first modes, stage it, check it, and propose it for approval, for a pm-os task whose envelope mode is forge/new-pack. Use when a Worker has been given such a task id.
---
# forge/new-pack — create a pack

You build in the staging area only. Each first mode is built by its own `forge/new-mode` child task,
so every mode gets its own design, review and checks. Follow the `forge:authoring` skill.

Step tags: `[model]` = your judgment · `[code: …]` = run the command. Track your stage in
`outputs/<id>/progress.json` (`{"stage": "design" | "modes" | "check"}`).

## Stage: design

1. `[code: python scripts/pmos.py task show <id>]` and `[code: python scripts/pmos.py catalog]` — the
   request, and what installed packs already cover. Reuse through `depends`, don't duplicate
   (`forge:compose-dont-copy`).
2. `[model]` Write `outputs/<id>/design.md`: the pack's scope and what it deliberately leaves to other
   packs; its roles; principles it adds or reuses; its first modes (one job each) and which one, if
   any, is its router.
3. `[code: python packs/forge/scripts/forge.py stage-pack --task <id> --name <name> --summary "<summary>" [--role <role>]]`
4. `[model]` Fill in the staged `pack.yaml` (depends, router, exports), `roles.yaml` and any new
   principles under `skills/principles/`.
5. If the design has more than three modes, stop for the PM: set stage to `"modes"`, submit
   `status: "blocked"` with `design.md` and `open_questions: ["Build these modes, or change the design?"]`.

## Stage: modes

6. For each first mode, create a child:
   `[code: python scripts/pmos.py task new --parent <id> --mode forge/new-mode --verb draft --approval none --inputs '{"pack": "<name>", "name": "<mode>", "purpose": "<purpose>", "into": "outputs/<id>/staged/<name>"}']`
7. Set stage to `"check"`, then `[code: python scripts/pmos.py task move <id> waiting]`.

## Stage: check

8. `[code: python packs/forge/scripts/forge.py lint outputs/<id>/staged/<name> --target packs/<name>]` — fix until PASS.
9. `[code: python scripts/pmos.py pack add outputs/<id>/staged/<name> --dry-run]` — fix until it passes;
   note the grants it lists.
10. `[code: python packs/forge/scripts/forge.py changes outputs/<id>/staged/<name> --target packs/<name>]`
11. Submit `status: "needs_approval"` with `design.md` as an artifact and one action:
    `{"system": "repo", "op": "sync_pack", "idempotency_key": "<id>-sync",
    "payload": {"staged": "outputs/<id>/staged/<name>", "target": "packs/<name>", "files": [<from step 10>]},
    "preview": "Create pack <name> (<n> modes, <n> files)"}`.
    In `summary`, say that after the Operator applies it the PM installs it with
    `python scripts/pmos.py pack add packs/<name> --approve-grants`, listing the grants from step 9.

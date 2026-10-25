---
name: forge-new-pack
description: Design a new pm-os pack with its roles, principles and first modes, stage it, check it, and propose it for approval, for a pm-os task whose envelope mode is forge/new-pack. Use when a Worker has been given such a task id.
---
# forge/new-pack — create a pack

Build only under `outputs/<id>/staged/`. Each first mode is a `forge/new-mode` child, so it gets its
own design and checks. Conventions: `forge:authoring`. Track the stage in
`outputs/<id>/progress.json` (`{"stage": "design" | "modes" | "check"}`).

## Stage: design

1. `[code: python scripts/pmos.py task show <id>]` and `[code: python scripts/pmos.py catalog]` — the
   request, and what installed packs already cover (reuse them through `depends`).
2. `[model]` Write `outputs/<id>/design.md`: the pack's scope and what it leaves to other packs; its
   roles; the principles it adds or reuses; its first modes (one job each) and its router, if any.
3. `[code: python packs/forge/scripts/forge.py stage-pack --task <id> --name <name> --summary "<summary>" [--role <role>]]`
4. `[model]` Fill in the staged `pack.yaml` (depends, router, exports), `roles.yaml` and any new
   principles under `skills/principles/`.
5. `[code: python scripts/pmos.py task result <id> outputs/<id>/result.json]` — only if the design
   has more than three modes: set stage `"modes"`, submit `status: "blocked"` with `design.md` and
   `open_questions: ["Build these modes, or change the design?"]`.

## Stage: modes

6. `[code: python scripts/pmos.py task new --parent <id> --mode forge/new-mode --verb draft --approval none --inputs '{"pack": "<name>", "name": "<mode>", "purpose": "<purpose>", "into": "outputs/<id>/staged/<name>"}']`
   per first mode; for the router, say so in `purpose` (it stages with `--router`). Children roll
   up to this task's approval and are reviewed with it.
7. `[code: python scripts/pmos.py task move <id> waiting]` after setting stage `"check"`.

## Stage: check

8. `[code: python packs/forge/scripts/forge.py lint outputs/<id>/staged/<name> --target packs/<name>]`
   — markers, names, coverage and `pmos lint` of the whole pack; fix until PASS.
9. `[code: python scripts/pmos.py pack add outputs/<id>/staged/<name> --dry-run]` — fix until it
   passes; note the grants it lists.
10. `[code: python packs/forge/scripts/forge.py changes outputs/<id>/staged/<name> --target packs/<name>]`
11. `[code: python scripts/pmos.py task result <id> outputs/<id>/result.json]` — `status:
    "needs_approval"`, `design.md` as an artifact, `outputs: {"staged": "outputs/<id>/staged/<name>"}`,
    one `repo.sync_pack` action (`idempotency_key: "<id>-sync"`, `payload: {"staged": …, "target":
    "packs/<name>", "files": <step 10>}`, `preview: "Create pack <name> (<n> modes, <n> files)"`).
    The summary gives the PM's install command with the grants from step 9:
    `python scripts/pmos.py pack add packs/<name> --approve-grants`.

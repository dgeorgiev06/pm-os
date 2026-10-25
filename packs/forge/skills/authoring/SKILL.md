---
name: forge-authoring
description: The pm-os conventions for authoring packs, modes, roles, skills and principles. Use whenever you design or edit a pm-os mode or pack.
---
# Authoring pm-os packs and modes

## Names

Pack `acme`; mode `acme/brief` (`modes/brief/`); role `acme/briefer` (`roles.yaml`); skill
`acme:domain/brief-style`; principle `acme:one-page` (`skills/principles/one-page/SKILL.md`, with
`kind: principle` and a one-line `check`). Inside a pack a bare name means that pack. Core items are `core:…`; another
pack's are `<pack>:…` (`<pack>/…` for modes and roles), used as `forge:compose-dont-copy` says.

## A mode

- `mode.yaml` (`contracts/mode.schema.json`): a one-line `summary`, which the CoS routes on;
  `accepts` and `returns` typed from `string number integer bool boolean list object doc_ref
  diff_ref`, a trailing `?` = optional; `calls`, version-pinned (`["*"]`: any mode the pack
  sees); `grants` (`read | draft | write`); `approval`; `principles`. Set `effort` or `dispatch`
  only when the mode differs from its role.
- `done:`: `must` lines all hold or the review fails; `should` lines set the score. A rule a
  script checks is `code: "python packs/<pack>/modes/<mode>/scripts/x.py {outputs.<name>}"`, run by
  pmos before review; `principle: <ref>` makes one blocking.
- `SKILL.md`: numbered steps, each tagged `[model]`, `[code: <command>]` or `[candidate-code]`, the
  first running `pmos task show <id>`, the last `pmos task result <id> outputs/<id>/result.json`.
- A gate: submit `status: "blocked"` with one open question; track the stage in
  `outputs/<id>/progress.json`. Children: `pmos task new --parent <id> …`, then `task move <id> waiting`.
- External changes are actions on systems the mode's `grants` hold at `draft` or `write`.
- Export it or list it in another mode's `calls`; otherwise nothing can start it.

## Tight text

Meet `core:tight-instructions`. `pmos lint` (run by forge.py lint) checks word budgets, step
structure, filler and copied text, per `lint:` in `pm-os.yaml`.

## Evals (eval@1)

Each case has `kind` and `covers` (the pack's own `mode:`, `script:`, `action:`, `router:` or
`principle:` refs). Admission requires:

| Feature | Needs | Where |
| --- | --- | --- |
| an exported mode | a golden case and a failure-path case (`failure: true`) | `modes/<mode>/evals/*.json` |
| a script (`scripts/`, `modes/*/scripts/`) or `actions:` handler | a conformance case | `evals/conformance/*.yaml` |
| the router | a workflow case | `evals/workflows/*.json` |

Fixtures go in `evals/fixtures/`; cases assume only core and `depends`. Steps get `$PACK`, `$FX`
(its fixtures) and `$CORE_BIN`. Check with `pmos eval --coverage <staged pack>`.

## A pack, versions and grants

`pack.yaml` (`contracts/pack.schema.json`): `requires: {core: ^0.4}`, `depends`, `exports`, and
optionally `router`, `actions` (`<system>.<op>: <script> [args]`) and `cos_section`.

Bump every changed mode's version and its pack's; `pmos pack add --upgrade` refuses otherwise.
Wider grants need the PM's `--approve-grants`.

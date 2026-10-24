---
name: forge-authoring
description: The pm-os conventions for authoring packs, modes, roles, skills and principles. Use whenever you design or edit a pm-os mode or pack.
---
# Authoring pm-os packs and modes

## Names

Pack `acme`; mode `acme/brief` (`modes/brief/`); role `acme/briefer`
(`roles.yaml`); skill `acme:domain/brief-style` (`skills/domain/brief-style/SKILL.md`); principle
`acme:one-page` (`skills/principles/one-page/SKILL.md`, with `kind: principle` and a one-line `check`).
Inside a pack a bare name means that pack, `exports` included. Core items are `core:…`; another
pack's are `<pack>:…` (`<pack>/…` for modes and roles), used as `forge:compose-dont-copy` says.

## A mode

- `mode.yaml` (`contracts/mode.schema.json`): a one-line `summary`, which the CoS routes on;
  `accepts` and `returns` typed from `string number integer bool boolean list object doc_ref
  diff_ref`, a trailing `?` = optional; `calls`, version-pinned (`["*"]`: any mode the pack
  sees); `grants` (`read | draft | write`); `approval`; `principles`; `rubric`. Set `effort` or
  `dispatch` only when the mode differs from its role.
- `SKILL.md`: numbered steps, each tagged `[model]`, `[code: <command>]` or `[candidate-code]`, the
  first running `pmos task show <id>`, the last `pmos task result <id> outputs/<id>/result.json`.
- A mid-way gate: submit `status: "blocked"` with one open question and track the stage in
  `outputs/<id>/progress.json`. Children: `pmos task new --parent <id> …`, then `task move <id> waiting`.
- Every external change is an action on a system the mode's `grants` hold at `draft` or `write`.
- Export it, or list it in another mode's `calls`, or nothing can start it.

## Tight text

Meet `core:tight-instructions`. `pmos lint` (run by forge.py lint) checks word budgets, the step
structure above, filler, and copied principles or paragraphs, per `lint:` in `pm-os.yaml`.

## Evals (eval@1)

Each case is one file with `kind` and `covers` (the pack's own `mode:`, `script:`, `action:`,
`router:` or `principle:` refs). Admission requires:

| Feature | Needs | Where |
| --- | --- | --- |
| an exported mode | a golden case and a failure-path case (`failure: true`) | `modes/<mode>/evals/*.json` |
| a script (`scripts/`, `modes/*/scripts/`) or `actions:` handler | a conformance case | `evals/conformance/*.yaml` |
| the router | a workflow case | `evals/workflows/*.json` |

Fixtures go in `evals/fixtures/`; cases assume only core and `depends`. In a step: `$PACK` (the
pack's folder), `$FX` (its fixtures), `$CORE_BIN` (core's helpers). Check with
`pmos eval --coverage <staged pack>`.

## A pack, versions and grants

`pack.yaml` (`contracts/pack.schema.json`): `requires: {core: ^0.3}`, `depends`, `exports`, and
optionally `router`, `actions` (`<system>.<op>: <script> [args]`) and `cos_section`.

Bump every changed mode's version and its pack's; `pmos pack add --upgrade` refuses otherwise.
Wider grants also need the PM's `--approve-grants`; until then pmos refuses the mode.

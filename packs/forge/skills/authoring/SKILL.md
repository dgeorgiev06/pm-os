---
name: forge-authoring
description: The pm-os conventions for authoring packs, modes, roles, skills and principles. Use whenever you design or edit a pm-os mode or pack.
---
# Authoring pm-os packs and modes

## Names

Pack `acme`; mode `acme/brief` (`modes/brief/`); role `acme/briefer`; skill
`acme:domain/brief-style`; principle `acme:one-page` (`skills/principles/one-page/SKILL.md`, with
`kind: principle` and a one-line `check`); standard `acme:standards/brief`. Bare names mean this
pack; others are `core:…` or `<pack>:…` (`<pack>/…` for modes and roles), used as
`forge:compose-dont-copy` says.

## A mode

- `mode.yaml` (`contracts/mode.schema.json`): a one-line `summary` (the CoS routes on it); `accepts`
  and `returns` typed from the schema's closed list (`?` = optional); `calls`, version-pinned
  (`["*"]`: any visible mode); `grants` (`read | draft | write`); `approval`; `skills`;
  `principles`. `effort`/`dispatch` only to differ from the role.
- Document-type principles and skills go on the mode, voice and style on the role; `validate`
  refuses one cited by both.
- A document's outline and rules are a standard (`contracts/standard.schema.json`); `standard:
  {ref, output}` adds its `check_doc.py` and judgment lines to `done`.
- `done:`: every `must` line holds or the review fails; `should` lines set the score.
  `code: "python packs/<pack>/modes/<mode>/scripts/x.py {outputs.<name>}"` runs before review;
  `principle: <ref>` makes one blocking.
- `SKILL.md`: numbered steps, each tagged `[model]`, `[code: <command>]` or `[candidate-code]`, the
  first `pmos task show <id>`, the last `pmos task result <id> outputs/<id>/result.json`.
- A gate: a `blocked` result with one question (stage in `outputs/<id>/progress.json`); children:
  `task new --parent <id>`, then `task move <id> waiting`.
- External changes are actions on systems granted at `draft` or `write`.
- Export it or put it in a mode's `calls`, or nothing can start it.

## Tight text

Meet `core:tight-instructions`; `pmos lint` checks it per `lint:` in `pm-os.yaml`.

## Evals (eval@1)

Each case has `kind` and `covers` (the pack's `mode:`, `script:`, `action:`, `standard:`,
`router:` or `principle:` refs). Admission requires:

| Feature | Needs | Where |
| --- | --- | --- |
| an exported mode | a golden case and a failure-path case (`failure: true`) | `modes/<mode>/evals/*.json` |
| a script (`scripts/`, `modes/*/scripts/`), `actions:` handler or standard | a conformance case (a standard: one passing, one `failure: true`) | `evals/conformance/*.yaml` |
| the router | a workflow case | `evals/workflows/*.json` |

Fixtures: `evals/fixtures/`; cases assume only core and `depends` (steps get `$PACK`, `$FX`,
`$CORE_BIN`). Check with `pmos eval --coverage <staged pack>`.

## Packs, versions, grants

`pack.yaml` (`contracts/pack.schema.json`): `requires: {core: ^0.5}`, `depends`, `exports`, and
optionally `router`, `actions` (`<system>.<op>: <script> [args]`), `overlays` (product → skills) and
`cos_section`.

Bump every changed mode's version and its pack's; `pmos pack add --upgrade` refuses otherwise.
Wider grants need the PM's `--approve-grants`.

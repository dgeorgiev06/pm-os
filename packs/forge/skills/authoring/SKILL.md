---
name: forge-authoring
description: The pm-os conventions for authoring packs, modes, roles, skills and principles. Use whenever you design or edit a pm-os mode or pack.
---
# Authoring pm-os packs and modes

The README's "Building blocks" and "Adding to a pack" sections are the reference for people; this
is the same set of rules for the Worker.

## Names

| Thing | Name | File |
| --- | --- | --- |
| Pack | `acme` (lowercase, hyphens) | `packs/acme/pack.yaml` |
| Mode | `acme/brief` | `packs/acme/modes/brief/mode.yaml` and `SKILL.md` |
| Role | `acme/briefer` | entry `briefer` in `packs/acme/roles.yaml` |
| Skill | `acme:domain/brief-style` | `packs/acme/skills/domain/brief-style/SKILL.md` |
| Principle | `acme:one-page` | `packs/acme/skills/principles/one-page/SKILL.md`, with `kind: principle` and `check: "…"` |

Inside a pack a bare name means that pack (`brief`, `briefer`, `domain/brief-style`, `one-page`),
including in `exports`. Core items are `core:…`; another pack's are `<pack>:…` (or `<pack>/…` for
modes and roles) and need that pack in `depends` and the item in its `exports`. SKILL.md frontmatter
needs a `description`; `name` is optional (`pmos render` generates it, and if present it must match).

## A mode

- `mode.yaml`: `name`, `version`, `contract: task@1`, a one-line `summary` (the CoS reads it),
  `verbs`, `accepts` (field: type, trailing `?` = optional), `returns` (output name: type; results
  carry them in `outputs`), `default_role`, `calls`
  (modes it may start as children, version-pinned; pmos refuses any other child; `["*"]` lets a
  router start any mode visible to its pack), `grants` (system: read | draft | write),
  `approval` (none | before_publish | before_execute), `risk`, `principles`, `rubric`, `evals`.
  Types are a closed set: `string`, `number`, `integer`, `bool`, `boolean`, `list`, `object`,
  `doc_ref`, `diff_ref` (a path or `scheme:` ref); anything else fails admission.
- `SKILL.md`: numbered steps, each tagged `[model]`, `[code: <command>]` or `[candidate-code]`.
  Start with `pmos task show <id>`; end with `pmos task result <id> outputs/<id>/result.json`.
- A gate that needs the PM mid-way: submit `status: "blocked"` with one open question, and track the
  stage in `outputs/<id>/progress.json`. Children: `pmos task new --parent <id> …`, then
  `pmos task move <id> waiting`; pmos re-queues the parent when they finish.
- Every external change is an `action` (system, op, idempotency_key, payload, preview), on a system
  the mode's `grants` hold at `draft` or `write`. Never write.
- Optional `effort` (`low | medium | high | max`: how hard the model reasons; tier picks the model)
  and `dispatch` (`background | foreground`); leave them out unless the mode really differs from its
  role. No built-in mode sets `dispatch: foreground`.
- Make it reachable: export it in `pack.yaml`, or list it in another mode's `calls`.

## Evals (eval@1)

Every case is one file in the eval@1 format (`contracts/eval.schema.json`, described in
`evals/framework/README.md`) with `kind` and `covers: [...]`, naming the pack's own features:
`mode:<pack>/<mode>`, `script:<path in the pack>`, `action:<system>.<op>`, `router:<pack>/<mode>`,
optionally `principle:<pack>:<name>`. The coverage rule, enforced at admission and by `validate`:

| Feature | Needs | Where |
| --- | --- | --- |
| an exported mode | a golden case, and a failure-path case (`failure: true`, golden or conformance) | `modes/<mode>/evals/*.json` (`kind: golden`) |
| a script in `scripts/` or `modes/*/scripts/` | a conformance case | `evals/conformance/*.yaml` (`kind: conformance`) |
| an `actions:` handler | a conformance case | `evals/conformance/` |
| the router | a workflow case: a golden case that runs modes together | `evals/workflows/*.json` |

Keep a pack's evals self-contained: fixtures in `evals/fixtures/`, and nothing beyond core and the
packs in `depends` (admission runs the conformance cases in a sandbox that holds only those). In a
conformance step, `$PACK` is the pack's folder, `$FX` its `evals/fixtures/`, and `$CORE_BIN` core's
helpers (`mkresult.py`, `advance.py`, `yset.py`). `forge.py stage-mode` writes a golden and a failure
case; `--script NAME` adds the script with its conformance case, and `--router` the workflow case.
Check with `pmos eval --coverage <staged pack>` (forge.py lint runs it) and
`pmos eval <pack> --kind conformance`.

## A pack

`pack.yaml`: `name`, `version`, `contract: pack@1`, `summary`, `requires: {core: ^0.3}`,
`depends`, optional `router` (an exported mode for goal-level asks), and `exports` for modes, roles,
skills and principles. Unexported items are internal to the pack. Optional: `actions` (handlers
`pmos action run` calls for approved actions, `<system>.<op>: <script in the pack> [args]`) and
`cos_section` (Markdown added to the CoS manual while the pack is installed).

## Versions and grants

Bump the version of every mode you change and of its pack, on any change: `pmos pack add --upgrade`
refuses an upgrade that doesn't raise the pack's version. A change that widens grants (a new
system, or read → draft → write) must also be re-approved by the PM with
`pmos pack add <path> --upgrade --approve-grants`; until then pmos refuses to run that mode.

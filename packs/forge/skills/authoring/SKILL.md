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
- At least one golden task in `evals/` with `envelope`, optional `fixtures`, and `expect` lines.
- Make it reachable: export it in `pack.yaml`, or list it in another mode's `calls`.

## A pack

`pack.yaml`: `name`, `version`, `contract: pack@1`, `summary`, `requires: {core: ^0.2}`,
`depends`, optional `router` (an exported mode for goal-level asks), and `exports` for modes, roles,
skills and principles. Unexported items are internal to the pack. Optional: `actions` (handlers
`pmos action run` calls for approved actions, `<system>.<op>: <script in the pack> [args]`) and
`cos_section` (Markdown added to the CoS manual while the pack is installed).

## Versions and grants

Bump the version of every mode you change and of its pack, on any change: `pmos pack add --upgrade`
refuses an upgrade that doesn't raise the pack's version. A change that widens grants (a new
system, or read → draft → write) must also be re-approved by the PM with
`pmos pack add <path> --upgrade --approve-grants`; until then pmos refuses to run that mode.

---
name: forge-authoring
description: The pm-os conventions for authoring packs, modes, roles, skills and principles. Use whenever you design or edit a pm-os mode or pack.
---
# Authoring pm-os packs and modes

## Names

| Thing | Name | File |
| --- | --- | --- |
| Pack | `acme` (lowercase, hyphens) | `packs/acme/pack.yaml` |
| Mode | `acme/brief` | `packs/acme/modes/brief/mode.yaml`; `SKILL.md` frontmatter `name: acme-brief` |
| Role | `acme/briefer` | entry `briefer` in `packs/acme/roles.yaml` |
| Skill | `acme:domain/brief-style` | `packs/acme/skills/domain/brief-style/SKILL.md`, `name: acme-domain-brief-style` |
| Principle | `acme:one-page` | `packs/acme/skills/principles/one-page/SKILL.md`, `name: acme-principles-one-page`, `kind: principle`, `check: "…"` |

Inside a pack a bare name means that pack. Core items are `core:…`; another pack's are `<pack>:…`
and need that pack in `depends` and the item in its `exports`.

## A mode

- `mode.yaml`: `name`, `version`, `contract: task@1`, a one-line `summary` (the CoS reads it),
  `verbs`, `accepts` (field: type, trailing `?` = optional), `returns`, `default_role`, `calls`
  (modes it may start as children, version-pinned), `grants` (system: read | draft | write),
  `approval` (none | before_publish | before_execute), `risk`, `principles`, `rubric`, `evals`.
- `SKILL.md`: numbered steps, each tagged `[model]`, `[code: <command>]` or `[candidate-code]`.
  Start with `pmos task show <id>`; end with `pmos task result <id> outputs/<id>/result.json`.
- A gate that needs the PM mid-way: submit `status: "blocked"` with one open question, and track the
  stage in `outputs/<id>/progress.json`. Children: `pmos task new --parent <id> …`, then
  `pmos task move <id> waiting`; pmos re-queues the parent when they finish.
- Every external change is an `action` (system, op, idempotency_key, payload, preview). Never write.
- At least one golden task in `evals/` with `envelope`, optional `fixtures`, and `expect` lines.

## A pack

`pack.yaml`: `name`, `version`, `contract: pack@1`, `summary`, `requires: {core: ^0.2}`,
`depends`, optional `router` (an exported mode for goal-level asks), and `exports` for modes, roles,
skills and principles. Unexported items are internal to the pack.

## Versions and grants

Bump the mode's version and the pack's version on any change. A change that widens grants (a new
system, or read → draft → write) must be re-approved by the PM with
`pmos pack add <path> --upgrade --approve-grants`; until then pmos refuses to run that mode.

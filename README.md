# pm-os

A modular, harness-neutral framework for automating product-management work. A Chief of Staff
delegates, installable **packs** of composable **modes** do the work, four agents are split by
permissions, **principles** define good work, and every output is reviewed. Phase 0 runs entirely
on skills plus a small deterministic CLI.

Nothing in the core depends on one vendor:

| Concern | Open format used |
| --- | --- |
| CoS instructions | `AGENTS.md`, generated from the `cos` pack (read natively by many agent harnesses) |
| Modes, skills, principles | `SKILL.md` folders with name/description frontmatter |
| Tools | MCP servers (Jira, docs, Slack…) mapped to grants |
| Contracts | JSON Schema in `contracts/` |
| State, registry, validation | `scripts/pmos.py`: plain Python, no LLM |
| Models | tiers (`small` / `mid` / `top`) mapped per provider in `pm-os.yaml` |

Harness-specific config is **generated** by `pmos render <adapter>` and never hand-edited.

Also in this repo:

- [`docs/`](docs/README.md) — the design and its reasoning: [architecture](docs/architecture.md),
  [decisions](docs/decisions.md), a [sprint-planning walkthrough](docs/walkthrough-sprint-planning.md),
  [phase 0 and the build plan](docs/phase-0-and-build-plan.md),
  [routing and delegation](docs/routing-and-delegation.md), the [DBOS runtime](docs/runtime-dbos.md),
  and [proposals](docs/proposals/todo-plan.md).
- [`examples/dbos/sprint_workflows.py`](examples/dbos/sprint_workflows.py) — two modes on a durable
  runtime (DBOS): `plan_next_sprint` and `track_sprint`.

## Quick start

```bash
pip install -r requirements.txt
python scripts/pmos.py validate          # core, every installed pack, and all references
python scripts/pmos.py catalog           # state/catalog.md + AGENTS.md for the CoS
python scripts/pmos.py catalog --pack pm # one pack's modes and what each accepts
```

Then pick a harness:

- **Claude Code**: `python scripts/pmos.py render claude-code`. This writes `CLAUDE.md` (imports
  `AGENTS.md`), subagents in `.claude/agents/` and skills in `.claude/skills/`. Map your MCP tool
  names under `adapters.claude-code.grants_to_tools` first; until you do, `render` warns that the
  Worker can still reach write tools.
- **Any harness that reads `AGENTS.md` and `SKILL.md` folders**: point it at this repo.
- **Your own runtime (any SDK or API)**: `python scripts/pmos.py render generic` writes one system
  prompt per agent, `models.json` (agent and role → model id) and `grants.json` to `build/generic/`.

Fill in `context/` (product, customers, glossary, roadmap) and replace
`packs/pm/skills/product/staking-prd/SKILL.md` with your existing staking PRD skill.

## Building blocks

| Unit | What it is | Lives in | Addressed as |
| --- | --- | --- | --- |
| **Pack** | The unit you install and share, like a plugin | `packs/<pack>/pack.yaml` | `pm` |
| **Mode** | One capability with a typed contract; composable | `packs/<pack>/modes/<mode>/` | `pm/prd` |
| **Router** | A pack's entry mode for goal-level asks | a mode named in `pack.yaml` | `pm/router` |
| **Role** | Config the Worker loads: persona, skills, context, tier | `packs/<pack>/roles.yaml` | `pm/doc-writer` |
| **Skill** | How-to knowledge, loaded by reference | `packs/<pack>/skills/<path>/` | `pm:domain/prd-structure` |
| **Principle** | A rule of good work with a one-line check | `packs/<pack>/skills/principles/<name>/` | `pm:plan-to-capacity` |
| **Agent** | Who executes, split by permissions | `agents/` (core), `packs/<pack>/agents/` | `worker` |

Inside a pack a bare name means "this pack". The core (the repo root) is the pack called `core`:
it holds the Worker, Operator and Reviewer agents, the infra skills, and the core principles.

Built-in packs:

| Pack | What it does |
| --- | --- |
| `cos` | The Chief of Staff manual (`AGENTS.md` is generated from it) and your todo list: `todos.py` for exact edits, `cos/todos` for planning, delegation only when you direct it |
| `pm` | PRDs, sprint planning, roadmap diffs, Jira tickets, release notes, and the `pm/router` |
| `forge` | Builds pm-os itself: `forge/new-mode` adds a mode to a pack, `forge/new-pack` creates a pack |

### Principles

Principles are how pm-os encodes judgment once and reuses it everywhere (the same idea as pstack's
`principle-*` skills). Each is a short `SKILL.md` with `kind: principle` and a one-line `check`.

- Modes and roles **cite** principles instead of restating rules. The Worker reads them before it
  starts; the Reviewer scores their `check` lines. Producer and reviewer judge against the same words.
- **Core principles** (`always: true`) apply to every task: grounded, no unapproved side effects,
  answers the envelope, honest self-check, usable summary. A task fails review if one fails.
- The improvement loop fixes the **highest layer** that solves a problem: a better principle
  improves every mode and role that cites it. See `quality/README.md`.

## How a pack registers

Packs don't register with the CoS. They register with the core **registry**, and the CoS reads what
the registry publishes, so any pack (including the CoS itself) can be swapped.

```bash
python scripts/pmos.py pack add path/to/pack --source third-party          # admission + grant review
python scripts/pmos.py pack add path/to/pack --source third-party --approve-grants
python scripts/pmos.py pack list
python scripts/pmos.py pack remove <name>
```

`pack add` runs **admission**: the pack and mode schemas are valid, the core version and dependency
packs match, every mode has golden evals, and every reference to another pack names something that
pack **exports**. It then shows the union of grants the pack's modes request and installs only with
`--approve-grants`. An upgrade that widens grants asks again. The pack is recorded in `packs.yaml`,
and `state/catalog.md` and `AGENTS.md` are regenerated, so the CoS sees the new pack as one line.

Guards: a pack can't be removed while another depends on it or while it has open tasks; the pack
that supplies the CoS (`cos_pack` in `pm-os.yaml`) can't be removed until another one is configured.
For a pack from another repo, clone it (e.g. into `vendor/`) and `pack add` the folder.

**Grants are enforced, not just recorded.** `pmos validate` and `pmos task new` refuse a mode
whose grants exceed what its pack was approved for. Widening a grant (a new system, or
read → draft → write) means bumping the pack's version and re-running
`pmos pack add <path> --upgrade --approve-grants`. `--dry-run` runs admission and lists the grants
without installing.

**Composition rules.** The CoS may start any mode a pack exports. A mode may call modes of its own
pack, plus exported modes of packs it lists in `depends`. Roles, skills and principles follow the
same rule. Everything else is internal to its pack.

**Routing.** When the PM names a concrete job ("draft a PRD for X"), the CoS goes straight to that
mode. Only goal-level asks go through a pack's router, which plans with the pack's own modes.

## How work flows

```
PM ──> CoS (AGENTS.md) ──pmos task new──> queued
                                            │  worker: pmos task move running
                                            ▼
            ┌──────── running ──task result──> in_review ──review──> done
            │            │                        │                    ▲
   children │   waiting <┘ (auto-requeued         ├─fail─> revise ─────┘ (≤ max_revisions, then failed)
  (pmos task│            when children finish)    │
     new    │                                     └─pass + approval needed─> awaiting_approval
   --parent)│                                                                  │ PM yes (pmos task approve)
            │   blocked <── result status "blocked" (a gate or a question)     ▼
            │      └─ CoS re-queues with the PM's answer                     approved ──Operator──> done
```

- **Only `pmos` changes task state.** Agents report results; the CLI validates them against
  `contracts/` and applies the transition. Every transition is a JSONL line in `traces/`.
- **Only the Operator writes to external systems**, and only for a task in `approved`.
- **Gates are states**: a mid-workflow decision is a `blocked` result with an open question;
  final approval is `awaiting_approval`.
- **Composition**: a mode creates child tasks with `--parent` and moves itself to `waiting`; pmos
  re-queues the parent when every child finishes. Budgets, depth limits and cycle checks apply.

## Repo layout

```
AGENTS.md                generated: the CoS manual from the cos pack + installed packs
pm-os.yaml               core config: version, tiers → model ids, adapters, cos_pack, defaults
packs.yaml               installed packs (managed by `pmos pack add/remove`)
roles.yaml               core roles (reviewer)
agents/                  core agents: worker, operator, reviewer
skills/infra/            core skills: envelope I/O, self-check
skills/principles/       core principles (apply to every task)
packs/cos/               pack.yaml, COS.md, agents/cos.md
packs/pm/
  pack.yaml              exports, router, depends, required core version
  roles.yaml             pm roles
  skills/                domain and product skills, pm principles
  modes/<mode>/          mode.yaml, SKILL.md, scripts/, evals/
contracts/               task, result, mode, roles and pack JSON Schemas
context/                 product knowledge, roadmap.yaml, decisions.log
quality/                 how review works
state/                   tasks, catalog, status board (managed by pmos)
traces/                  one JSONL event per state change
outputs/<task id>/       artifacts and result.json
```

## Adding to a pack

The easy way is to ask the CoS: "add a mode to pm that drafts the weekly leadership update" runs
`forge/new-mode`. It designs the contract and golden task first, stages a skeleton under
`outputs/<task>/staged/` with `packs/forge/scripts/forge.py`, fills it in, lints it, and runs a
dry-run admission. You approve the file list like any other change, the Operator copies the files
into `packs/`, and you run the install command the result gives you. `forge/new-pack` does the same
for a whole pack, building each first mode as its own `forge/new-mode` child task.

By hand:

- **Mode**: `packs/<pack>/modes/<mode>/` with `mode.yaml` (name `<pack>/<mode>`), `SKILL.md`
  (frontmatter `name: <pack>-<mode>`) and at least one golden task in `evals/`. Add it to the
  pack's `exports.modes` if the CoS or other packs should use it.
- **Role**: an entry in the pack's `roles.yaml`, citing skills and principles.
- **Principle**: `packs/<pack>/skills/principles/<name>/SKILL.md` with `kind: principle` and `check`.

Then `python scripts/pmos.py validate && python scripts/pmos.py catalog`, and re-render your adapter.

## From skills to code: the codify ladder

Every step in a mode's `SKILL.md` carries a tag:

- `[model]` — judgment: prioritizing, writing, reviewing. Stays with the model.
- `[candidate-code]` — the model does it today, but it is rule-shaped (building JQL, mapping fields).
- `[code: script]` — already a script; agents run it instead of reasoning about it.

Promote a `[candidate-code]` step when you can write a unit test for it, or when traces show it is
high-volume or keeps failing review. Three steps are already codified: `check_prd.py`,
`capacity.py` and `dedupe.py`.

## Later: moving to a durable runtime

When the CoS thread needs to stay free during long work, approvals wait for days, or the sprint
tracker must run unattended, move the runtime to an SDK service with a durable workflow engine
(e.g. DBOS on Postgres). `pmos` transitions become workflow state, codified scripts become steps,
`waiting` becomes child workflows, gates become `recv` waits. Packs, modes, roles, skills,
principles and contracts carry over unchanged.

## Evals

`python scripts/pmos.py eval [pack | pack/mode …]` renders each golden task to
`build/evals/…/prompt.md` (for the agent) and `grader.md` (for the reviewer, with the principles
and rubric). Set `eval.command` in `pm-os.yaml` to any non-interactive runner and it runs each case
against an isolated state directory.

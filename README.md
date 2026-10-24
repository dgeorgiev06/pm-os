# pm-os

pm-os automates product-management work with agents you can audit. You talk to a **Chief of Staff
(CoS)** agent. It turns each request into a task for one **mode** (a typed capability such as
`pm/prd`), a Worker does the work, a separate Reviewer checks it, and nothing changes in Jira, docs
or the roadmap until you approve it. A small deterministic CLI, `pmos`, owns all task state and
checks every hand-off.

Today pm-os runs as **phase 0**: agents are skills and subagents inside an agent harness (such as
Claude Code), `pmos` is a Python script, and state is files. Later the same packs move to a durable
runtime ([DBOS](docs/runtime-dbos.md)). Formats are open (AGENTS.md, SKILL.md, MCP, JSON Schema),
and harness config is generated, never hand-edited.

## Quick start

```bash
pip install -r requirements.txt
alias pmos="python scripts/pmos.py"   # this README uses the alias; agents run the long form
pmos validate                         # core, every installed pack, and all references
pmos catalog                          # writes state/catalog.md and AGENTS.md for the CoS
pmos catalog --pack pm                # one pack's modes and what each accepts
```

Then:

1. **Pick a harness.**
   - Claude Code: `pmos render claude-code` writes `CLAUDE.md` (imports `AGENTS.md`), subagents in
     `.claude/agents/` (one Worker per model tier) and skills in `.claude/skills/`. First map your MCP
     tool names under `adapters.claude-code.grants_to_tools` in `pm-os.yaml`; until you do, `render`
     warns that the Worker can still reach write tools.
   - Any harness that reads `AGENTS.md` and `SKILL.md` folders: point it at this repo.
   - Your own runtime (any SDK or API): `pmos render generic` writes a system prompt per agent,
     `models.json` and `grants.json` to `build/generic/`.
2. **Add your context.** Fill in `context/` (product, customers, glossary, roadmap) and replace
   `packs/pm/skills/product/staking-prd/SKILL.md` with your own PRD skill.
3. **Ask for work.** Say "draft a PRD for X" to the CoS. It creates a `pm/prd` task, delegates it,
   and replies with a short digest, then with an approval request before anything is published.

## How work flows

Four agents, split by what they may touch: the **CoS** (talks to you, creates tasks), the
**Worker** (does all thinking work, under a role), the **Reviewer** (scores results in a fresh
context) and the **Operator** (the only one that writes to external systems, and only for approved
tasks). Only `pmos` moves a task between states, and every transition is a line in `traces/`.

```mermaid
stateDiagram-v2
  [*] --> queued: CoS runs pmos task new
  queued --> running
  running --> in_review: result done / needs_approval
  running --> waiting: created child tasks
  waiting --> queued: all children finished (automatic)
  running --> blocked: a gate or an open question
  blocked --> queued: CoS re-queues with your answer
  in_review --> done: passed, no approval needed
  in_review --> awaiting_approval: passed, approval needed
  in_review --> revise: failed (up to max_revisions, then failed)
  revise --> running
  awaiting_approval --> approved: your yes (pmos task approve)
  awaiting_approval --> revise: your changes
  approved --> done: Operator ran the actions
  done --> [*]
```

[docs/walkthrough-sprint-planning.md](docs/walkthrough-sprint-planning.md) follows one request
through every step.

## Building blocks

| Unit | What it is | Lives in | Written as |
| --- | --- | --- | --- |
| **Pack** | The unit you install and share, like a plugin | `packs/<pack>/pack.yaml` | `pm` |
| **Mode** | One capability with a typed contract (`accepts`, `returns`, grants, approval) | `packs/<pack>/modes/<mode>/` | `pm/prd` |
| **Router** | A pack's entry mode for goal-level asks; it plans with the pack's own modes | `router:` in `pack.yaml` | `pm/router` |
| **Role** | What the Worker becomes for a task: persona, skills, context, tier, principles | `packs/<pack>/roles.yaml` | `pm/doc-writer` |
| **Skill** | How-to knowledge, loaded by reference | `packs/<pack>/skills/<path>/SKILL.md` | `pm:domain/prd-structure` |
| **Principle** | A rule of good work with a one-line `check` the Reviewer scores | `packs/<pack>/skills/principles/<name>/SKILL.md` | `pm:plan-to-capacity` |
| **Agent** | Who executes: CoS, Worker, Reviewer, Operator | `agents/`, `packs/<pack>/agents/` | `worker` |
| **Envelope** | A task's work order: mode, verb, inputs, acceptance, risk, approval, budget; immutable once queued | `state/tasks/<id>.json` ([schema](contracts/task.schema.json)) | `T-20261024-001` |
| **Grant** | What a mode may do in one system: `read`, `draft` or `write`; you approve a pack's grants when you install it | `grants:` in `mode.yaml` | `jira: read` |
| **Action** | One external change a result proposes (system, op, payload, preview, idempotency key); it runs only after your approval | `actions` in `result.json` | `jira.create_issue` |

**Writing a reference.** The last column is the full form, which works everywhere. Inside a pack a
bare name means "this pack": `prd`, `doc-writer`, `domain/prd-structure`, `plan-to-capacity` (this
is how `exports`, roles and modes list the pack's own items). The repo root is the pack `core` (the
Worker, Operator and Reviewer, infra skills, core principles), so core items are `core:infra/…`.
Using another pack's item needs that pack in your `depends` and the item in its `exports`. Mode
references (`--mode`, `calls`) may pin a version: `pm/prd@^0.2`. SKILL.md `name` frontmatter is
optional; `pmos render` generates it (`pm-prd`, `pm-domain-prd-structure`).

Built-in packs:

| Pack | What it does |
| --- | --- |
| `cos` | The Chief of Staff manual ([COS.md](packs/cos/COS.md), copied into `AGENTS.md`) and your todo list ([routing and delegation](docs/routing-and-delegation.md)) |
| `pm` | PRDs, sprint planning, roadmap diffs, Jira tickets, release notes, and the `pm/router` |
| `forge` | Builds pm-os itself: `forge/new-mode`, `forge/new-pack`, and `forge/review-framework` (re-runs a framework review) |

| Other terms | Meaning |
| --- | --- |
| Verb | The kind of work: `plan`, `draft`, `analyze`, `execute` or `review`. `--verb` is optional when a mode lists one |
| Tier | A role's model size: `small`, `mid` or `top`, mapped to model ids in `pm-os.yaml` |
| Gate | Where a task waits for you: mid-way (a `blocked` result with one question) or at the end (`awaiting_approval`) |
| Admission | The checks `pmos pack add` runs before it installs a pack (below) |
| Golden eval | A sample task in a mode's `evals/`, with `expect` lines a grader checks; every mode needs one |
| Conformance eval | A deterministic check of pm-os itself, in `evals/framework/`; no model |
| Phase 0 | Today's setup (above); later phases are in [the build plan](docs/phase-0-and-build-plan.md) |

## What pmos enforces

Prompts ask agents to behave; these rules hold in code whatever an agent does.

- **State.** Only `pmos` changes task state. `task move` can't take a task out of `in_review` (only
  `task review` does, or `task result` itself for a child reviewed with its parent), and only
  `task approve` puts it in `approved`. A hand-edited task file is refused.
- **Composition.** The CoS may start any mode a pack exports. A child task (`--parent`) needs a
  `running` parent, and its mode must be in the parent mode's `calls` (`["*"]` means any mode the
  pack can see), at the pinned version. A pack sees its own items plus what packs in its `depends`
  export. Call depth and cycles are checked.
- **Grants.** `validate` and `task new` refuse a mode whose grants exceed what its pack was approved
  for, and `validate` flags approved grants edited by hand in `packs.yaml`. `task result` refuses an
  action on a system the mode isn't granted (at `draft` or `write`).
- **Approval.** `task new` can't set a weaker approval or a lower risk than the mode's; only a child
  may lower its approval, when its parent's approval covers it (its actions then roll up to the
  parent's gate). `task result` refuses actions that no approval would ever cover. The Operator runs
  `pmos action run <id>`, which refuses unless the task is `approved` and its actions are exactly
  the ones you approved.
- **Budgets.** `task result` refuses a result whose `usage` exceeds the task's budget (`max_usd`,
  `max_minutes`) unless its status is `failed`, and a summary over 80 words. A child's spend counts
  against its parent's (and every ancestor's) `max_usd`.
- **Review.** The Reviewer gives a verdict for every checklist line (pmos refuses missing ones), and
  pmos computes pass or fail ([quality/README.md](quality/README.md)).
- **Versions.** `pack add --upgrade` refuses unless the pack's version goes up.

## Installing packs

```bash
pmos pack add path/to/pack --source third-party                  # admission; lists requested grants
pmos pack add path/to/pack --source third-party --approve-grants # install
pmos pack add packs/pm --upgrade --approve-grants                # upgrade (the version must go up)
pmos pack add path/to/pack --dry-run                             # admission and grants, no install
pmos pack list
pmos pack remove <name>
```

**Admission** checks the pack's and modes' schemas, the core version and `depends`, a golden eval
for every mode, and that every reference to another pack names something it exports. `pack add`
then lists the grants the pack's modes request and installs only with `--approve-grants`; an
upgrade that widens a grant asks again. The pack goes into `packs.yaml`, and `state/catalog.md` and
`AGENTS.md` are regenerated, so the CoS sees it as one line. Packs register here, not with the CoS,
so any pack can be swapped, even the one that supplies the CoS (`cos_pack` in `pm-os.yaml`).

Any change to a pack bumps its `version` (and each changed mode's). A pack can't be removed while
another depends on it or it has open tasks. For a pack from another repo, clone it (e.g. into
`vendor/`) and `pack add` the folder.

## Adding to a pack

The easy way is to ask the CoS: "add a mode to pm that drafts the weekly leadership update" runs
`forge/new-mode`. It designs the contract and golden eval first, stages the mode under
`outputs/<task>/staged/`, lints it and runs a dry-run admission. You approve it like any other
change, the Operator copies it into `packs/`, and you run the install command the result gives you.
`forge/new-pack` does the same for a whole pack.

### A mode, by hand

1. Copy a working mode: `cp -r packs/pm/modes/prd packs/<pack>/modes/<mode>`.
2. Edit `mode.yaml` ([schema](contracts/mode.schema.json)). Required:
   `name` (`<pack>/<mode>`), `version`, `contract` (`task@1`), `summary` (one line; the CoS routes
   on it), `accepts` (`input: type`, a trailing `?` = optional), `returns`, `default_role` and
   `approval` (`none`, `before_publish` or `before_execute`). Optional: `verbs`, `calls`, `grants`,
   `risk`, `principles`, `rubric`, `acceptance`, `evals`.
3. Edit `SKILL.md`: a `description` in the frontmatter, then numbered steps, each tagged (see the
   next section). Start with `task show <id>`; end with `task result <id> outputs/<id>/result.json`.
4. Rewrite `evals/golden-01.json`: `name`, `envelope` (`verb`, `mode`, `inputs`, `acceptance`,
   `risk`, `approval`), optional `fixtures`, and `expect` (lines a grader checks).
5. Make it reachable: add the bare name to `exports.modes` in `pack.yaml` (for the CoS and other
   packs), or to another mode's `calls`. `validate` warns about a mode that is neither.
6. Bump the pack's `version`, run `pmos validate`, then
   `pmos pack add packs/<pack> --upgrade` (add `--approve-grants` if grants widened), and re-render
   your harness.

Other units:

- **Role**: an entry in `roles.yaml` with `agent`, `tier`, `persona`, `skills`, `context`,
  `principles` and `rubric`.
- **Principle**: `packs/<pack>/skills/principles/<name>/SKILL.md` with `description`,
  `kind: principle` and a one-line `check`. Cite principles instead of restating rules: the Worker
  reads them and the Reviewer scores the same `check` lines.
- **Action handler**: `actions: {"<system>.<op>": "<script> [args]"}` in `pack.yaml` lets
  `pmos action run` apply that action with a script; actions without one are applied by the
  Operator with its tools.

The `forge:authoring` skill ([SKILL.md](packs/forge/skills/authoring/SKILL.md)) has the full
conventions.

## Step tags: the codify ladder

Every step in a mode's `SKILL.md` carries a tag:

- `[model]`: judgment (prioritizing, writing, reviewing). Stays with the model.
- `[candidate-code]`: the model does it for now, but it's rule-shaped (building JQL, mapping fields).
- `[code: <command>]`: already a script. Run it; don't redo the work by hand.

Promote a `[candidate-code]` step to a script when you can write a unit test for it, or when traces
show it is high-volume or keeps failing review. Codified steps live in each mode's `scripts/`
folder (e.g. `check_prd.py`, `capacity.py`) and in pack scripts (`todos.py`, `forge.py`).

## Evals

| Layer | What it checks | How to run |
| --- | --- | --- |
| Golden evals (per mode) | A mode's output on its sample tasks, graded against `expect`, principles and rubric | `pmos eval [pack \| pack/mode …]` renders `prompt.md` and `grader.md` per case to `build/evals/`; set `eval.command` in `pm-os.yaml` to run them |
| Conformance evals (the framework) | pm-os's own behaviour: the cases from the framework reviews, in code, no model | `pmos eval --framework [clarity \| performance \| modularity \| composability]` ([details](evals/framework/README.md)) |
| Framework review (judgment) | What code can't check, scored like the original reviews | ask the CoS for a framework review, or `pmos task new --mode forge/review-framework --inputs '{"aspect": "clarity"}'` |

With `eval.command` set, each golden case runs with its own state, traces and outputs folders
(`PMOS_OUTPUTS_DIR`) and distinct task ids; a golden task's `gates` list answers the mode's gates so
multi-stage modes run to the end. Set `eval.grader_command` too and each run is graded into
`score.json`, with the pass rate in `build/evals/summary.json`.

## Repo layout

Besides the folders in the Building blocks table:

```
AGENTS.md          generated: the CoS manual (from the cos pack) + installed packs
pm-os.yaml         core config: version, tiers -> model ids, adapters, cos_pack, defaults
packs.yaml         installed packs (managed by `pmos pack add/remove`)
context/           product knowledge, roadmap.yaml, decisions.log
state/, traces/    tasks, catalog, status board; one JSONL event per state change (pmos writes these)
outputs/<task>/    artifacts and result.json
evals/framework/   conformance evals for pm-os itself
```

## More

[docs/](docs/README.md) has the design in depth (architecture, decisions, diagrams, routing,
phases, the durable runtime), [quality/README.md](quality/README.md) explains how work is reviewed,
and [examples/dbos/](examples/dbos/sprint_workflows.py) sketches modes on the durable runtime.

# pm-os

A modular, harness-neutral framework for automating product-management work: a Chief of Staff
that delegates, pluggable **modes** that do the work, four agents split by permissions, and a
review-and-improve loop. Phase 0 runs entirely on skills plus a small deterministic CLI.

Nothing in the core depends on one vendor:

| Concern | Open format used |
| --- | --- |
| CoS instructions | `AGENTS.md` (read natively by many agent harnesses) |
| Modes and shared skills | `SKILL.md` folders with name/description frontmatter |
| Tools | MCP servers (Jira, docs, Slack…) mapped to grants |
| Contracts | JSON Schema in `contracts/` |
| State, routing, validation | `scripts/pmos.py`: plain Python, no LLM |
| Models | tiers (`small` / `mid` / `top`) mapped per provider in `pm-os.yaml` |

Harness-specific config is **generated** by `pmos render <adapter>` and never hand-edited.

Also in this repo:

- [`docs/PM-Agent-OS-Architecture.pdf`](docs/PM-Agent-OS-Architecture.pdf) — the full design: architecture
  diagram, Chief of Staff, workflow manager and state, modes, agents and roles, review loop, build plan.
- [`examples/dbos/sprint_workflows.py`](examples/dbos/sprint_workflows.py) — what two modes look like on a
  durable runtime (DBOS): `plan_next_sprint` and `track_sprint`.

## Quick start

```bash
pip install -r requirements.txt
python scripts/pmos.py validate     # modes, roles, skills, agents, contracts
python scripts/pmos.py catalog      # writes state/catalog.md, the CoS's menu of modes
```

Then pick a harness:

- **Claude Code**: `python scripts/pmos.py render claude-code`. This writes `CLAUDE.md` (imports
  `AGENTS.md`), subagents in `.claude/agents/` and skills in `.claude/skills/`. Map your MCP tool
  names under `adapters.claude-code.grants_to_tools` first; until you do, `render` warns that the
  Worker can still reach write tools.
- **Any harness that reads `AGENTS.md` and `SKILL.md` folders**: point it at this repo. Add a 20-line
  adapter in `render_*` if it wants files in a specific place.
- **Your own runtime (any SDK or API)**: `python scripts/pmos.py render generic` writes one system
  prompt per agent, `models.json` (agent and role → model id) and `grants.json` to `build/generic/`.
  Give each agent a shell limited to `python scripts/pmos.py …` plus its granted MCP tools.

Fill in `context/` (product, customers, glossary, roadmap) and replace
`skills/product/staking-prd/SKILL.md` with your existing staking PRD skill.

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
- **Gates are just states**: a mid-workflow decision (like approving sprint priorities) is a
  `blocked` result with an open question; final approval is `awaiting_approval`.
- **Composition**: a mode creates child tasks with `--parent` and moves itself to `waiting`; pmos
  re-queues the parent when every child finishes. Budgets, depth limits and cycle checks are enforced.

## Repo layout

```
AGENTS.md            CoS operating manual (harness-neutral)
pm-os.yaml           tiers → model ids, adapters, defaults
roles.yaml           role sheet: persona, skills, context, tier, rubric
agents/              cos, worker, operator, reviewer (frontmatter: tier + grants)
modes/<author>/<name>/
  mode.yaml          manifest: accepts/returns, default role, calls, grants, approval, rubric
  SKILL.md           the workflow, with [model] / [code: …] / [candidate-code] step tags
  scripts/           codified steps
  evals/             golden tasks (+ fixtures). No evals, no registration.
skills/{infra,domain,product}/   shared skills, referenced by roles
contracts/           task, result, mode and roles JSON Schemas
context/             product knowledge, roadmap.yaml, decisions.log
quality/             baseline rubric applied to every task
state/               tasks, catalog, status board (managed by pmos)
traces/              one JSONL event per state change
outputs/<task id>/   artifacts and result.json
```

## Adding a mode

1. Create `modes/<author>/<name>/` with `mode.yaml`, `SKILL.md` (frontmatter `name: <author>-<name>`)
   and at least one golden task in `evals/`.
2. Use an existing role or add one to `roles.yaml`.
3. `python scripts/pmos.py validate && python scripts/pmos.py catalog`, then re-render your adapter.

Third-party modes: vendor them into their own folder, add it to `paths.modes`, and label it in
`sources` (`org` or `third-party`). The CoS prefers local, then org, then third-party when two match.
Pin versions in envelopes and `calls` (`core/prd@^1`).

## From skills to code: the codify ladder

Every step in a mode's `SKILL.md` carries a tag:

- `[model]` — judgment: prioritizing, writing, reviewing. Stays with the model.
- `[candidate-code]` — the model does it today, but it is rule-shaped (building JQL, mapping fields).
- `[code: script]` — already a script; agents run it instead of reasoning about it.

Promote a `[candidate-code]` step when you can write a unit test for it, or when traces show it is
high-volume or keeps failing review. Three steps are already codified as examples:
`check_prd.py`, `capacity.py` and `dedupe.py`.

## Later: moving to a durable runtime

When the CoS thread needs to stay free during long work, approvals wait for days, or the sprint
tracker must run unattended, move the runtime to an SDK service with a durable workflow engine
(e.g. DBOS on Postgres). The pieces map directly: `pmos` transitions become workflow state, codified
scripts become steps, `waiting` becomes child workflows, gates become `recv` waits. Modes, roles,
skills and contracts carry over unchanged.

## Evals

`python scripts/pmos.py eval [mode …]` renders each golden task to `build/evals/…/prompt.md` (for
the agent) and `grader.md` (for the reviewer). Set `eval.command` in `pm-os.yaml` to any
non-interactive runner and it runs each case against an isolated state directory.

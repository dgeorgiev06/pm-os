# pm-os implementation spec

The one document to build from: the target model, the gaps between it and `main`, and the staged
work to close them. Written from a framework review of `main` at 193c043, and the single home for
that work — the interim plan docs it consolidates were never committed.

**Goal.** Get PM and engineering work done in a structured, predictable way, through one thread that
never blocks, with the ability to plan ahead — and keep the pieces few enough to hold in your head.

---

# 1 · The model

## Three independent axes

| Axis | Carries | Lives on |
| --- | --- | --- |
| **Envelope** | authority and lifecycle position; the harness abstraction | `worker`, `reviewer`, `operator` |
| **Mode** | one capability and its pipeline | `modes/<mode>/` |
| **Tier** | cost | mode > role > agent > default |

Independence is the whole fix. A planner is a mode at `tier: top`; a researcher is a mode at
`tier: small` feeding it through `$from`. Neither needs a new envelope or a new role. Conflating
these produced eleven roles for twelve modes.

## Six components

| Component | Its one job |
| --- | --- |
| Envelope | who may do what, and when in the lifecycle |
| Mode | one focused capability with a contract |
| Tier | `small` / `mid` / `top` |
| Pack | modes plus the policy they share; `kind: capability \| adapter` |
| Role | *optional* persona; only when two or more modes share it |
| Workflow | which envelopes get a turn: `default: [worker, reviewer]` |

Nothing else is a concept.

## Three declaration surfaces

Each envelope has a different unit of work and its own place to declare it. This is the symmetry the
framework is missing one third of.

| Envelope | Unit | Declared in | Today |
| --- | --- | --- | --- |
| `worker` | **step** | `steps:` on the mode | **missing** |
| `reviewer` | **checklist line** | `done:`, the standard's `judgment:`, each principle's `check:`, the role's `rubric:`, the task's `acceptance` / `instructions` | exists, assembled by `review_checklist()` |
| `operator` | **action** | `emits:` on the mode + the pack's `actions:` handler map | `emits:` **missing** |

Consequences that fall out, each already settled:

- **Workflow entries name envelopes, never step ids.** `[worker, reviewer]`, not `[draft, review]`.
- **A step needing a different tier is a different task** — tier selects the subagent, so the
  boundary is an envelope boundary with a `$from` edge. This is why `pm/rank-backlog` exists.
- **A mid-pipeline external write is a task boundary** — one approval covers one action batch,
  digest-checked, so operator work is never interleaved with steps.
- The pipeline is therefore **pure up to `submit`**: reads and local writes only. That is what makes
  a worker step replaceable by a script.

## How the reviewer knows what to review

It receives a computed checklist, never instructions. `review_checklist()` assembles, in order:
core principles (the five with `always: true`) → the standard's code line and `judgment:` lines →
the mode's `done.must` → the task's `acceptance` → the PM's `instructions` → gated children's whole
done blocks, prefixed → `done.should`, non-core cited principles, the role's `rubric`.

Already mechanical, and worth preserving exactly: `code` lines arrive **settled** (pmos ran them at
`task result`); `cmd_task_review` refuses a missing line, missing evidence, or a failed line with no
`fix`; **pmos computes the pass** — every core and must line holds, and
`5 × (share of should lines that hold) ≥ 4`. The reviewer cannot declare pass.

*Consequence to document, not change:* the should threshold is 80%, so a mode with fewer than five
should lines effectively needs all of them. Writing few `done.should` lines makes a mode stricter,
not more lenient.

How to add a constraint: a rule for every document of a type → the standard's `judgment:`; for this
mode's output → `done.must`; measurable → `done.must` as a `code:` line so it settles before review;
voice or style → the role's `rubric:`; cross-cutting → a principle with a `check:`; one task only →
`--acceptance`.

## Contracts that must not move

- **Envelope and result** (`contracts/task.schema.json`, `result.schema.json`, `$from`) — how data
  moves between agents. This is the abstraction software replaces later.
- **The codify ladder** — `[model]` → `[candidate-code]` → `[code: <cmd>]`, per step, contract
  unchanged.
- **The state machine and its approval gate** — `pmos` is the only writer of task state; nothing
  external happens before the PM's yes, and `cmd_action_run` refuses if the action set changed.
- **Declared workflows** — the on-ramp to a durable runtime. Prose in `COS.md` is not portable.

---

# 2 · Mode shape

## Seven phases

Every mode is a subset, in order. A phase may be empty — but deliberately.

| Phase | Tag | Does |
| --- | --- | --- |
| load | code | `pmos task show`. Always first, generated |
| gather | code / candidate-code | read systems of record into a typed file |
| reduce | code | deterministic computation |
| **decide** | **model** | the judgment — the only phase needing inference |
| check | code | validate against a standard or invariant |
| build | code | render the artifact, assemble actions |
| submit | code | `pmos task result`. Always last, generated |

> **A `[model]` step reads declared files and writes declared files.**

Both shapes declared in `mode.yaml`. A model step is then a typed transform, and promoting it to code
is mechanical — the declared `in`/`out` is already the replacing script's contract and its fixture.

## `steps:` and `workflows:`

```yaml
steps:
  - { id: load,   tag: code,           run: "pmos task show {task}" }          # generated
  - { id: refs,   tag: candidate-code, in: [inputs.refs], out: refs.json,
      shape: "[{ref, kind, fact}]" }
  - { id: draft,  tag: model,          in: [refs.json], out: [prd.md] }
  - { id: check,  tag: code,           in: [prd.md],
      run: "check_doc.py --standard pm:standards/prd {prd.md}" }
  - { id: submit, tag: code,           run: "pmos task result {task} {result.json}" }  # generated

workflows:
  default: [worker, reviewer]
  fast:    [worker]

emits: [docs.publish]
```

Paths relative to `outputs/<id>/`. `steps:` takes `mode.yaml` from 17 fields to 18 — a deliberate
trade: every `[code:]` line leaves `SKILL.md`, step order and IO leave prose, and SKILL-vs-contract
drift becomes unexpressible. Information moves from prose into contract.

## `SKILL.md`

Only the model steps — one block per `model` step id, in pipeline order:

```markdown
## draft
- **Given** refs.json — each fact with the ref it came from.
- **Decide** what each section must say so every requirement is testable.
- **Write** prd.md to the standard's sections, each claim cited inline as [ref].
- **Refuse** a requirement you can't name a test for — raise it in open_questions.
- **On revise** start from the existing prd.md, address every note, change nothing else.
```

`task show` interleaves `steps:` and these blocks into one numbered list, so the Worker's view is
unchanged.

## Layout, derived not mandated

> A pack contains exactly the directories its manifest implies, and nothing else.

One `pack_layout(manifest)` consumed by both `stage-pack` (scaffold) and `check_pack` (admission), so
template and check cannot drift.

| Directory | Required iff |
| --- | --- |
| `modes/`, `roles.yaml` | `kind: capability` |
| `evals/workflows/` | `router:` declared |
| `evals/conformance/` | any script, handler, standard or channel |
| `standards/` | `exports.standards` non-empty |
| `channels/` | `exports.channels` non-empty |
| `agents/`, `COS.md` / `COS-section.md` | `cos:` / `cos_section:` declared |
| `skills/principles/<p>/` | each `exports.principles` entry |
| `scripts/` | a pack-level handler, or a script used by ≥2 modes |

```
modes/<mode>/
  mode.yaml    contract + steps + workflows + emits
  SKILL.md     one block per model step
  skills/      domain skills cited by this mode only
  scripts/     the code steps
  evals/       golden · failure · one conformance case per script
```

Mode directory closed to that set. Skill path's first segment closed to
`principles/ domain/ product/ infra/`.

**A pack must not:** contain an unexplained directory or top-level file; hold a pack-level script
serving exactly one mode; be a capability pack with zero exported modes or an adapter pack with any
mode or role; reference another pack's directory; declare one fact in two places; carry `TODO:`
markers, `__pycache__`, or `.gitkeep` in a non-empty directory.

---

# 3 · Decisions settled

Each reversed an earlier proposal in this repo's docs.

| Decision | Replaces |
| --- | --- |
| Generate what would otherwise be validated | four new linters; a SKILL-vs-contract checker |
| `worker` stays one envelope; specialisation is mode + tier | splitting it into planner / researcher / drafter |
| The operator's unit is an **action**, not a step | a `core/operator` role |
| `tier` joins `resolve_setting`, so roles stop carrying cost | the single-consumer role waiver |
| A step needing a different tier is a **different task** | `rank-backlog` as a judgment call |
| A mid-pipeline external write is a **task boundary** | interleaving operator work into a pipeline |
| Workflow entries name envelopes, never step ids | the `[draft, review]` sketch |
| `role:` per step: not built — zero users after the split | adding it for symmetry |
| pm owns its three handlers until a second pack needs them | a `trackers` adapter pack now |

---

# 4 · Gaps

Each reproduced against the code.

### Easy and intuitive

| Gap | Evidence |
| --- | --- |
| A mode cannot declare workflows | `--workflow` and `task.schema.workflow` exist; written at `pmos.py:2132`, **never read**; no `workflows` in `mode.schema.json` |
| A mode cannot declare steps | order and IO live in SKILL prose; intermediate shapes appear inside step text |
| `tier` lives only on a role | absent from `mode.schema.json`; `resolve_setting` chains `effort`/`dispatch` but not `tier` |
| A role's tier is ignored unless its agent declares `tiers:` | only `worker` has the list, so `core/reviewer`'s `tier: mid` does nothing |
| CoS routing is prose | no `router:` in `packs/cos/pack.yaml`; `COS.md` at a raised 1100-word budget to fit one routing line |
| No pack shape control | `check_pack` enforces referential integrity only; five packs disagree on layout; `forge:authoring` vs `pm:domain/prd-structure` |

### Predictable and quality

| Gap | Evidence |
| --- | --- |
| **Reviewer independence is broken** | `--for-review` prints `## Producer self-check` — the producer's claims on the exact criteria being scored — while `agents/reviewer.md` opens *"never the producer's reasoning"* |
| **Approval identity is forgeable** | `cmd_task_approve` takes `--by` as free text; Workers hold `shell:pmos`; forge's `check_staged` tests only `state == approved`, so a Worker can rewrite `packs/` |
| Nothing checks a checklist line is **judgeable** | `done.must` accepts any string — `must: "The PRD is good"` passes admission and becomes a line a reviewer must score |
| A `done` code line can be **vacuous** | `review-framework`'s only code line checks the repo is clean, not that the report is any good (#10) |
| Golden evals have never run | `eval.command: ""`; 60 cases, 0 executed |
| No action pm proposes has a handler | `jira.create_issue`, `roadmap.apply_diff`, `docs.publish` live in SKILL prose; declared handlers are only `comms.send*`, `todos.apply_diff`, `repo.sync_pack` |
| Grants unenforced where unmapped | `jira:*` and `comms:send` map to `[]`; `render` warns the agent *"inherits all tools"* |
| `docs:write` overloaded | mapped to `[Write, Edit]` (local files) but reads as "publish externally" |

### Modular and extendable

| Gap | Evidence |
| --- | --- |
| Additive bumps break pins | `^0.x` pins the minor; `stage-mode` calls `bump_minor` for additive changes |
| One concern across three packs | `release-comms/scripts/send.py` shells into `cos/modes/notify/scripts/` |
| External interfaces per-vendor | audiences a constant in `build_actions.py`; the ticket mode named for Jira; no doc-target registry |
| Role layer doing capability's job | 11 roles, pm 6 for 5 modes, most single-consumer |

### Cost and visibility

| Gap | Evidence |
| --- | --- |
| Cost not measured | `tokens_in`/`tokens_out` defined, never read; recorded results show `usd: 0.0` |
| Nothing bounds a live run | budgets checked only at `task result` |
| Nothing runs unattended | phase 0 has no scheduler |

---

# 5 · Implementation

## Stage A — Lock

**A1 · Integrity.** Remove `## Producer self-check` from `task show --for-review`; add
`omitClaudeMd: true` to the reviewer subagent so project context cannot anchor it either. Take
approval identity from the harness instead of `--by`. Harden forge's `check_staged`: refuse agent
names, re-lint at apply, confine `--files` to the target. Scope grants with `disallowedTools` and
per-subagent `mcpServers`.
**Exit:** a producer cannot approve its own work; a reviewer sees neither producer claims nor project
context.

**A2 · `pmos doctor`.** Report every declared mechanism with zero executions: eval kinds with no
runner, schema properties no code reads, `done` line types never evaluated, documented enforcement
with no covering case, conformance cases that cannot fail. Add a **per-adapter enforcement matrix**
(§6).
**Exit:** doctor reproduces the known inert inventory; CI fails on a new entry. Run it after every
stage.

**A3 · Free deletions and harness truth.** `depends` → `^[a-z0-9-]+$`, pins stripped. Drop `effort`,
`dispatch`, `merge_child_actions` from `mode.schema.json`. Cut tightness stylometry (word budgets,
filler list, sentence averages, shingles), keep the structural checks. Flip `supports_effort` and
`supports_background` to true, add `xhigh` to `EFFORT_LEVELS`, render `effort:` and `background:`.
**Exit:** `validate`, `lint`, conformance green with fewer rules; effort and background are applied,
not printed.

**A4 · The three axes.** `tier` into `resolve_setting`; `tiers:` on the `reviewer` and `operator`
agents; `role` optional on a mode. Delete every role that only carried a tier or stood in for a
capability.
**Exit:** pm has two roles, both with ≥2 consumers; `core/reviewer`'s tier applies.

**A5 · Declare the pipeline.** `steps:` in `mode.schema.json` with `in`/`out`, validated at runtime
against `contracts/`. Generate `load`, `submit` and every `[code:]` line in `SKILL.md`. Wire the
`workflows:` stub, consulted by `cmd_task_result` instead of always routing to `in_review`.
**Exit:** deleting a SKILL's command block changes nothing; `fast: [worker]` skips the reviewer with
no code change.

## Stage B — Extend

**B1 · Declare side effects.** `emits:` on modes, refused at admission without a handler and at
`task result` if undeclared. Ship pm's three handlers. Split `docs:write` into `files:write` and
`docs:publish`; map `jira:*` and `comms:send`. Add `docs` to `external_systems`.
**Exit:** zero handler-less action kinds; the Operator's `manual` path is the exception.

**B2 · Make checklists checkable.** Lint `done` lines for judgeability — a `must` names an artifact
location or a measurable property. Extend the mutation gate to `done` code lines: remove what the
line claims to check and it must fail.
**Exit:** `must: "The PRD is good"` is refused; no `done` code line passes with its subject removed.

**B3 · Decide the golden layer.** Set `eval.command` and run the 60 cases once under `eval.max_usd`,
or delete the kind.
**Exit:** doctor reports zero inert eval kinds.

**B4 · Lock the shape.** `kind:`, `pack_layout()`, the closed mode directory and skill taxonomy, the
negative constraints of §2.
**Exit:** a stray directory fails admission; `channels` installs as an adapter; a pack-level script
serving one mode is refused.

**B5 · Consolidate and genericise.** One `comms-director` absorbing `channels`,
`release-comms/release-notify` and `cos/notify`; both forwarders deleted; audiences from
`context/channels.yaml`. A registry per interface family — channel, tracker, doc target.
`cos/router` as a mode; pm's routing line out of `COS.md`.
**Exit:** zero cross-pack directory references; adding a channel, tracker or doc target is a config
entry.

## Stage C — Hold

**C1 · Forge controls.** `forge.py lint --metrics` computing simplicity, modularity and quality, and
refusing a staged change that worsens any of them without a `pmos decide` entry. A contract-budget
case asserting schema property counts. Reuse promoted from `should` to `must`. No new pack without a
recorded rejected alternative. `doctor` run against staged work. `forge.py lint --mutate` on
`failure: true` cases. An `evals/framework/structure/` group so every control has a case that fails
when the control is removed.
**Exit:** the ratchet refuses a deliberately bloated staged pack; `decisions.log` holds every
deliberate increase in complexity.

**C2 · Borrowed, once locked.** Automatic context offload of large tool results to `outputs/<id>/`.
A typed resume payload replacing `blocked` plus `progress.json`. A one-file mode — contract and skill
together, evals required only on export — to cut time-to-first-run, the widest gap against
comparable frameworks.

---

# 6 · Harness: Claude Code now, Codex later

The adapter under-declares what Claude Code supports.

| pm-os today | Claude Code offers | Closes |
| --- | --- | --- |
| `supports_effort: false` | `effort: low\|medium\|high\|xhigh\|max` per subagent | effort is a label |
| `supports_background: false` | `background: true`; spawned subagents start backgrounded anyway | the blocking thread |
| `EFFORT_LEVELS` lacks `xhigh` | five levels | an unreachable level |
| grants → `tools` allowlist | `disallowedTools`, per-subagent `mcpServers` | grants unenforced |
| "load every skill `task show` lists" as a model step | `skills:` preloads full content at startup | a model step per mode |
| reviewer independence by prose | `omitClaudeMd: true` | context anchoring |
| budget checked at `task result` | `maxTurns` bounds a live run | nothing bounds a live run |
| forge stages under `outputs/<id>/staged/` | `isolation: worktree` | — |

There is **no per-subagent thinking setting** — it is inherited from the session. Effort is the only
reasoning dial; do not design for thinking.

**The Codex boundary.** Two kinds of native field:

- **Enforcement the model depends on** — tool and MCP scoping, reviewer context isolation, effort,
  background. Every adapter must provide these or the guarantees are prose. `effort_map` already
  anticipates it (`openai: {param: reasoning_effort}`).
- **Harness optimisations** — `isolation: worktree`, `skills:` preload, `autoCompactWindow`,
  `experimental.cacheTtl`. Use them, but keep the framework's mechanism as fallback. In particular
  **do not replace forge's staging with worktrees** — forge is how the framework extends itself, and
  it must run on both adapters.

`doctor`'s enforcement matrix reports, per guarantee, whether this adapter enforces it natively, by
framework convention, or not at all. That makes the second adapter a known quantity rather than a
discovery.

---

# 7 · Out of scope, deliberately

- **Model-decided orchestration.** The plan stays a declared artifact with typed `$from` edges, not
  a todo list in a context window. This is the framework's reason to exist.
- **Agents as tools.** It would collapse the worker / reviewer / operator boundary the approval gate
  depends on.
- **`role:` per step, a `trackers` adapter pack, per-platform operator agents.** No consumer yet.
- **A durable workflow engine.** `workflows:` and `steps:` are its on-ramp; the engine is phase 3.

---

# 8 · Verify after every stage

```
python scripts/pmos.py validate && python scripts/pmos.py lint \
  && python scripts/pmos.py eval --coverage \
  && python scripts/pmos.py eval --all --kind conformance \
  && python scripts/pmos.py doctor
```

The 158-case conformance count moves in B5 as notify, channels and release cases re-home. Set the new
baseline deliberately rather than letting it drift.

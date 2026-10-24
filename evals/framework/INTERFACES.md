# Interfaces the fixes implement

Contract first: these are the names and shapes the conformance cases in `evals/framework/` expect.
Implement to this file; if an interface has to change, change it here and in the cases together.

Error messages are free text. Cases match only the **key word** given for each refusal
(case-insensitive regex), on stdout or stderr, plus a non-zero exit. Task ids are captured from
output, never assumed.

Owner = the review folder whose fix agent implements it (see `findings/README.md`).

## Already built (this change)

| Interface | Shape |
| --- | --- |
| `pmos eval --framework [REVIEW …] [--case GLOB] [--json]` | Runs `scripts/framework_eval.py`: a pass/fail table (or the JSON summary with `--json`), `build/framework-evals/latest.json`, exit 1 if any case fails. `scripts/framework_eval.py` also takes `--root DIR`, `--cases-dir DIR`, `--out FILE`, `--keep`, `--jobs N`. |

## Modularity

| # | Interface | Shape and rules | Cases |
| --- | --- | --- | --- |
| M1 | Parent must be running | `task new --parent P` is refused unless P is `running`. Key word: `running`. | child-needs-running-parent |
| M2 | `calls` enforced, with pins | With `--parent`, the child's mode name must match an entry in the parent mode's `calls`, and it resolves with that entry's version pin. Key word: `calls`. | child-outside-calls-refused, gtm-children-respect-calls-and-pins, doc-claims-backed |
| M3 | `calls: ["*"]` | A mode (typically a router) may declare `calls: ["*"]`: any mode visible to its pack (own pack, or exported by a pack in `depends`) may be a child. `mode.schema.json` accepts `"*"`. Visibility errors still apply (key word: `depends`). | router-star-calls |
| M4 | Actions tied to grants | `task result` refuses an action whose `system` isn't in the mode's `grants` at `draft` or `write`. Key word: `grant`. Note: `pm/jira-tickets` and `pm/sprint-planning` then need `jira: draft` (and `roadmap: draft`), which is a grant widening: bump pm and re-approve. | action-system-must-be-granted |
| M5 | `actions:` in pack.yaml | `actions: {"<system>.<op>": "<script path relative to the pack> [fixed args…]"}`. forge declares `repo.sync_pack`, cos declares `todos.apply_diff`. `pack.schema.json` accepts the key. | action-run-dispatches-pack-handler |
| M6 | `pmos action run ID [--key IDEMPOTENCY_KEY]` | Refuses unless the task is `approved` (key word: `approved`) and its actions still hash to the last approval's `actions_sha` (key word: `sha`, `hash`, `changed` or `tamper`). For each action, runs the handler the **task's own pack** declares for `system.op`: `python <pack dir>/<script> [fixed args…] <action file>`, where the action file is JSON `{"task_id": …, "action": {…}}`, cwd is the repo root, `PMOS_ROOT` is set and exit 0 means applied. Actions with no handler are listed as `manual` (the Operator runs them with its tools). Writes `<outputs>/<id>/applied.json` (`applied`, `skipped`, `failed`, `manual`), prints JSON, and moves the task to `done` when every action was applied by a handler. Keys already in `applied.json` are skipped; after a failed handler the rest are skipped, the task stays `approved` and the exit is 1. | action-run-guards, action-run-dispatches-pack-handler |
| M7 | Generic Operator | `agents/operator.md` runs `pmos action run <id>` and names no pack paths; `pm-os.yaml` has no `todos:` grant mapping; `scripts/pmos.py` has no `== "cos"` (or other pack-name) special case. The CoS agent is found through `cos_pack` (the agents that pack defines). | operator-names-no-pack |
| M8 | Transition ownership | `task move` can't leave `in_review` (only `task review`) and can't enter `approved` or `awaiting_approval` (only `task approve` / `task review`). Key words: `review`, `approve`. `awaiting_approval → revise` (the PM's "change X") and `approved → done` (the Operator) stay on `task move`. | review-cannot-be-bypassed |
| M9 | Task-file integrity | pmos stores a hash of each task file it writes (beside it or in the file); a command that loads a task file edited by hand refuses. Key word: `edit`, `hash`, `tamper`, `integrity` or `modified`. | hand-edited-task-detected, action-run-guards |
| M10 | Grant-approval record | `pack add --approve-grants` records what was approved somewhere other than `grants_approved` alone (built: append-only `state/grant-approvals.jsonl`, one `{ts, pack, version, grants}` line per approval), and `validate` errors when `packs.yaml` `grants_approved` differs from the record. Key word: `grant`. Built-in packs must have a committed record, so a clean `validate` stays OK. | hand-edited-grants-detected |
| M11 | Artifacts under outputs | A relative artifact `ref` must resolve inside `<outputs dir>/<task id>/` (or the folder of the task's parent chain or descendants: sprint-planning lists its child's ticket preview, a forge/new-mode child under forge/new-pack lists files staged in the parent's folder); scheme refs (`jira:`, `doc:`, `url:` … i.e. `^[a-z]+:`) are allowed. Key word: `outputs`. | artifact-outside-outputs-refused |
| M12 | Generic `origin` | Envelope `origin: {"pack": "<pack>", "ref": "<free text>"}`; `task new --origin PACK:REF`. `--todo` and the `td-` pattern are removed from the core (`todos.py` and `COS.md` use `--origin cos:td-12`). | origin-is-generic |
| M13 | A pack's CoS section | pack.yaml `cos_section: <file>`: Markdown that pmos appends to AGENTS.md while the pack is installed. forge's "Building the system itself" moves there, so removing forge removes it. | removed-pack-not-referenced |
| M14 | References to missing packs | `validate` warns (or errors) when an installed pack's text (SKILL.md, COS.md, agents) names a mode (`<pack>/<mode>`) or path (`packs/<pack>/`) of a pack that isn't installed. Output names the pack and says `not installed`. | removed-pack-not-referenced |
| M15 | Instructions only at the top | `--instructions` is refused with `--parent` (key word: `instructions`). Children inherit the parent's (C7). | forged-child-instructions-refused |
| M16 | Approval and risk floor | `task new` refuses `--approval` weaker than the mode's (none < before_publish < before_execute; key word `approval`) or `--risk` lower than the mode's (key word `risk`). Exception: a child may lower its approval when the parent's envelope approval is at least the mode's; pmos then records `"approval_from": "<parent id>"` at the top level of the task state. | approval-floor, approval-rollup-recorded |
| M17 | Actions that can never run | `task result` refuses actions on a task whose approval is `none` and that has no `approval_from`. Key word: `approval` or `never`. | unrunnable-actions-flagged |
| M18 | Grants claim | Either render tools per role/mode from approved grants (`build/generic/grants.json` gets keys containing `/`), or `docs/decisions.md` stops saying grants are "enforced at run time" and says what is enforced. | grants-claim-matches-code |
| M19 | `pmos task state ID --json`, `pmos pack path NAME` | `task state` prints the task state JSON (with `"state"`), or just the state without `--json`; `pack path` prints the pack's directory. `todos.py` and `forge.py` use them (no reads of `state/tasks` or `packs.yaml`, no `parents[3]`). | pack-scripts-use-pmos |
| M20 | `forge.py apply` source check | `apply STAGED --target packs/NAME` refuses unless STAGED is under `<outputs>/<id>/staged/` and task `<id>` is `approved`. Key word: `outputs`, `staged` or `approved`. (forge's `repo.sync_pack` handler calls the same check.) | forge-apply-source-checked |

## Composability

| # | Interface | Shape and rules | Cases |
| --- | --- | --- | --- |
| C1 | Failure cascade | When a task moves to `failed`, every `queued` or `blocked` task whose `depends_on` names it moves to `failed` with a note `dependency <id> failed`; parents wake as usual. | failure-cascades |
| C2 | Upgrade re-checks dependents | `pack add --upgrade` runs the admission checks of every installed pack that depends on the upgraded one, and refuses if any fails, naming it. `--force` installs anyway. | upgrade-rechecks-dependents |
| C3 | `task show` fallback | When the task's `mode@version` is no longer installed, `task show` uses the stored `mode_dir`. | task-show-survives-upgrade |
| C4 | Closed type vocabulary | `accepts`/`returns` types: `string`, `number`, `integer`, `bool`, `boolean`, `list`, `object`, `doc_ref`, `diff_ref`, each optionally ending in `?`. Anything else fails admission/validate (key word `type`). A `doc_ref`/`diff_ref` input is a string that is an existing path or a `scheme:` ref; otherwise refused naming the input. | input-types-checked |
| C5 | Result `outputs` | `result.outputs: {"<name>": <value>}`. For status `done`/`needs_approval`, every non-optional name in the mode's `returns` must be present, unknown names are refused (naming them), and values are type-checked (`doc_ref`/`diff_ref`: existing path or scheme ref; `list`: array; …). `returns` entries may end in `?`. | result-outputs-match-returns |
| C6 | `$from` input refs | An input value may be `{"$from": "<task id>", "output": "<name>"}`. At `task new`: the source task exists and its mode's `returns` has that name (refused naming the output otherwise), and the source id is added to `envelope.depends_on`. At `task move … running`: resolved from the source's `result.outputs` into `inputs_resolved` (top level of the task state); `task show` prints the resolved values. | from-ref-wiring |
| C7 | Instructions flow down | A child inherits the parent's `instructions`; `task show` prints them labelled with the parent they came from. | instructions-inherited |
| C8 | Budgets drawn down | `task result` on a child refuses when the summed `usage.usd` of the parent and all its children would exceed the parent's `max_usd`. Key word: `budget`. | children-budget-summed, doc-claims-backed |

## Performance

| # | Interface | Shape and rules | Cases |
| --- | --- | --- | --- |
| P1 | A worker per tier | `render claude-code` writes `.claude/agents/worker-small.md`, `worker-mid.md`, `worker-top.md` with `model:` set from the tier's alias; `render generic` writes `build/generic/worker-<tier>.system.md` and `models.json` `agents["worker-<tier>"]`. A plain `worker` may remain. | render-worker-per-tier |
| P2 | `delegate to:` | `task show` prints a line `delegate to: worker-<tier>` from the task's role tier; COS.md tells the CoS to use it. | task-show-delegate-line |
| P3 | Dispatch rule | COS.md: after every subagent returns, run `python scripts/pmos.py task list --state queued` and delegate each queued task, in parallel in the background when independent. | cos-dispatches-queued |
| P4 | Budget on result | `task result` refuses when `usage.usd > budget.max_usd` or `usage.seconds > budget.max_minutes × 60`. Key word: `budget`. | budget-enforced-on-result |
| P5 | `pmos stats [--mode M] [--json]` | From the traces. JSON: `{"modes": {"<mode>": {"tasks": n, "usd_total": x, "usd_mean": x, "p50_seconds": x, "p90_seconds": x, "first_pass_rate": x, "revise_after_approval_rate": x}}}`. | stats-command |
| P6 | `PMOS_OUTPUTS_DIR` | Overrides `paths.outputs` everywhere (artifact checks, forge staging, scripts). `pmos eval` sets it per case, and task ids are distinct across the cases of one eval run. | eval-runs-isolated |
| P7 | Grader | `eval.grader_command` in pm-os.yaml with `{grader_file}` and `{output_file}`; its stdout is JSON `{"passed": bool, "lines": [{"line": …, "pass": bool}]}`, saved as `score.json` in the case folder. `build/evals/summary.json`: `{"cases": n, "passed": n, "pass_rate": x}`. | eval-graded-with-gates |
| P8 | Scripted gates | Golden task key `gates: ["<answer to gate 1>", …]`; `prompt.md` gets a "Gate answers" section and the runner continues through gates instead of "stop there". sprint-planning's golden task has `gates`. | eval-graded-with-gates |
| P9 | Per-line review verdicts | `task show ID --checklist` prints JSON `[{"id": "<line id>", "group": "core"\|"mode"\|"role"\|"mode rubric"\|"role rubric"\|"pm instructions", "text": …}]`; principle lines use the principle id (`core:grounded`), rubric lines `mode-rubric-<n>` / `role-rubric-<n>`. `task review ID --verdicts FILE [--note …]` with FILE `{"score": 0-5, "lines": [{"id": …, "pass": bool, "note": …}]}`: every checklist id needs a verdict (key word `missing`, `line` or `verdict`); pmos computes passed = every `core` line passes and score ≥ 4, and stores `lines` in `result.review`. `--passed` is no longer trusted. | review-pass-computed |
| P10 | Summary length | `task result` refuses a summary over 80 words. Key word: `summary` or `words`. | summary-length-checked |
| P11 | Default acceptance | mode.yaml `acceptance: [...]`; used for the envelope when `--acceptance` isn't given. Every built-in mode declares it. | mode-default-acceptance |
| P12 | `check_plan.py` | `packs/pm/modes/sprint-planning/scripts/check_plan.py PLAN.json CAPACITY.json`: exit 1 with `over capacity` when the sum of `committed[].points` exceeds `committed_points`; the SKILL runs it. | plan-capacity-check |
| P13 | `merge_child_actions` | mode.yaml `merge_child_actions: true`: at the parent's `task result`, pmos appends the actions of its `done` children whose approval rolled up to it (M16), skipping idempotency keys already present. | child-actions-merged |
| P14 | Gated children skip review | A child with envelope approval `none` whose parent's approval isn't `none` goes from a `done` result straight to `done`; its work is reviewed in the parent. | gated-child-skips-review |
| P15 | Two counters | `revisions` counts failed reviews (against `max_revisions`); `change_requests` counts PM "change X" moves (`awaiting_approval → revise`). | revision-counters-separate |
| P16 | Stable-first `task show` | Mode, role and principles come before anything task-specific (the id, envelope, history). | task-show-stable-first |

## Clarity

| # | Interface | Shape and rules | Cases |
| --- | --- | --- | --- |
| L1 | Bare `exports.modes` | `exports.modes: [brief]` means `<pack>/brief`; prefixed names keep working. | references-written-once |
| L2 | Generated SKILL names | SKILL.md `name` is optional for modes, skills and principles (if present it must still match); `render` writes the generated name into the copies it makes. | references-written-once |
| L3 | Unexported-mode warning | `validate` prints a `warn:` line naming a mode that is neither exported nor in any `calls` of its pack. | validate-warns-unexported |
| L4 | One version rule | `pack add --upgrade` refuses unless the new version is higher than the installed one. Key word: `version`. README and forge:authoring state the same rule. | one-version-rule, regression-grant-widening-refused |
| L5 | `--verb` default | Optional when the mode declares exactly one verb. | verb-defaults |
| L6 | CLI help | Every option of every pmos subcommand has help text (including `task new --workflow`). | cli-help-complete |
| L7 | Mode recipe | The README's "Adding to a pack" section names every field `contracts/mode.schema.json` requires, or `pmos new mode` exists. | readme-mode-recipe |

## Helpers the cases use (no new interface)

`evals/framework/fixtures/bin/` holds small scripts that set up cases without depending on any one
owner's interface. `mkresult.py` adds an `outputs` map only when `contracts/result.schema.json`
has an `outputs` property; `advance.py` reviews with `--verdicts` when `task review --help` lists
it, and with `--passed true --score 5` otherwise. So a case owned by one review keeps working
while another review's contract changes.

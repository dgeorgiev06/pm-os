# Evals: the eval@1 standard, and core's conformance cases

Every pack's features are tested by **eval@1** cases ([`contracts/eval.schema.json`](../../contracts/eval.schema.json)),
and any hub that implements eval@1 can run them; `pmos eval` is the reference runner. Core is the
pack `core`, and this folder is its conformance folder: cases for pm-os itself, first built from the
four framework reviews in [`findings/`](findings/README.md), then from approved additions.

- **Conformance** (`kind: conformance`, code only, no model): this folder for core, one subfolder per
  group; `packs/<pack>/evals/conformance/*.yaml` for a pack. Regression cases (`regression: true`)
  cover what the reviewers confirmed works, and must always pass.
- **Golden** (`kind: golden`, model-graded): `packs/<pack>/modes/<mode>/evals/*.json` for one mode,
  `packs/<pack>/evals/workflows/*.json` for modes run together (a router's goal → its children).
- **Judgment:** the `forge/review-framework` mode re-runs a framework review on demand. It runs
  core's cases first, then judges what code can't, against the original review question.

New interfaces are specified in [`INTERFACES.md`](INTERFACES.md).

## Run

```bash
python scripts/pmos.py eval --all --kind conformance          # core + every pack: a table per pack, totals
python scripts/pmos.py eval pm --kind conformance             # one pack; pm/prd = the cases covering that mode
python scripts/pmos.py eval pm --kind golden                  # render (and with eval.command, run) golden cases
python scripts/pmos.py eval --coverage                        # each pack's features and the cases covering them
python scripts/pmos.py eval core --kind conformance --json    # eval-result@1 on stdout and in build/evals/results.json
python scripts/pmos.py eval --framework modularity            # alias for core's cases, by group (or several)
python scripts/pmos.py eval --framework --case 'approval-*'   # cases matching a glob (--case works for all forms)
python scripts/framework_eval.py modularity --keep            # keep each case's temp copy to debug it
```

`pmos eval` runs conformance first, then golden; it exits non-zero on any failure. Golden cases
only render (`prompt.md`, `grader.md` under `build/evals/`) until `eval.command` is set in
`pm-os.yaml`; then each runs in its own state, traces and outputs folders, graded by
`eval.grader_command`, and the run stops starting cases once their summed `usage.usd` reaches
`eval.max_usd`.

## The coverage rule

`covers` names the case's own pack's features: `mode:<pack>/<mode>`, `script:<path relative to
the pack>` (core: relative to the repo root), `action:<system>.<op>` (a pack.yaml `actions:`
handler), `router:<pack>/<mode>`, and optionally `principle:<pack>:<name>`. Admission (`pack add`,
including `--dry-run`) and `validate` refuse a pack unless:

- every exported mode has a golden case and a failure-path case (`failure: true`, golden or conformance);
- every file under `scripts/` and `modes/*/scripts/` has a conformance case (core: `scripts/*.py`);
- every `actions:` handler has a conformance case;
- the router has a workflow case (in `evals/workflows/`).

The error lists each missing feature and the folder to add a case to. Admission then runs the
pack's conformance cases in a **sandbox**: a copy of the repo holding only core, the CoS pack, the
packs in `depends` and the pack itself, and refuses on any failure. `--with-golden` also runs the
golden cases there (through `eval.command`; they cost money). So a pack's evals are self-contained:
fixtures in `packs/<pack>/evals/fixtures/`, nothing beyond core and `depends`.

With `--framework`, the table shows case, finding, result and the first failing expectation; a JSON
summary goes to `build/framework-evals/latest.json`, and the exit code is non-zero if any case fails.
`scripts/framework_eval.py` also takes `--root DIR` (test another tree with these cases),
`--out FILE` and `--jobs N`.

To re-run a whole review, with judgment, ask the CoS for one, or create the task directly:
`python scripts/pmos.py task new --mode forge/review-framework --verb review --inputs '{"aspect": "modularity"}'`.

## How a case runs

Each case gets a fresh temporary copy of the repo (a pack's case: of its sandbox), without `.git`,
`build/`, `state/tasks/`, `traces/`, `outputs/` and `context/todos.yaml`. Setup runs, then the steps
run in order as `bash -c` with cwd = the copy, and each step's expectations are checked before the
next one runs. The case stops at its first failing expectation. A case never runs itself (a case
that runs `pmos eval` skips its own name further down).

## Case format (eval@1)

### Conformance

One YAML file per case, in `evals/framework/<group>/` (core) or `packs/<pack>/evals/conformance/`:

```yaml
kind: conformance
name: child-outside-calls-refused     # unique in the pack; also the file name
covers: [script:scripts/pmos.py]      # the features it tests (see the coverage rule)
failure: true                         # optional: it tests a failure path (a refusal, an error exit)
finding: modularity#1                 # core: <review>#<n> in findings/<review>.md (#good = a strength), or request:<name>
owner: modularity                     # default: the folder (core) or the pack
severity: high                        # from the finding
regression: false                     # true: confirmed to work today; must keep passing
desc: What the desired behaviour is.
setup:                                # optional
  install: [gtm]                      # fixture packs: copied to packs/<name>, then `pmos pack add --approve-grants`
  copy: {packs/x-forge: packs/x-forge}  # fixtures/<from> -> <to in the copy>, without installing
  files: {path/in/copy.txt: "content"}
steps:
  - name: optional label for the table
    run: $PMOS task new --mode pm/prd --verb draft --inputs '{"goal":"g"}'
    capture: {P: '(T-\d{8}-\d{3,})'}  # VAR: regex; group 1 (or the match) of the LAST match in stdout, else stderr
    expect:                           # all optional
      exit: 0                         # 0 (default) | nonzero | any | <n>
      stdout: [regex, ...]            # each must match (re.search, multiline); also stderr, output (= both)
      stdout_not: [regex, ...]        # none may match; also stderr_not, output_not
      task:                           # read from state/tasks/<id>.json
        id: $P
        state: 'in_review|revise'     # full-match regex
        fields: {envelope.verb: '^draft$', result.actions: 'part-publish'}  # dotted path -> regex on the value (JSON-encoded unless a string)
        absent: [some.field]
      files:                          # paths relative to the copy; globs (with **) allowed
        exists: [outputs/x.md]
        absent: ['outputs/T-*']
        contains: {AGENTS.md: 'regex'}
        not_contains: {AGENTS.md: 'regex'}
```

Captured values are environment variables for later steps (`$P`) and are substituted in
expectations. Steps also get `$PMOS` (`python scripts/pmos.py`), `$PY`, `$FX` (the case's fixtures:
`evals/framework/fixtures`, or `packs/<pack>/evals/fixtures`), `$PACK` (the pack's folder in the
copy), `$CORE_BIN` (core's helpers, `evals/framework/fixtures/bin`), `$REPO` (the copy) and, for
core's cases, `$FORGE` and `$TODOS`. Every inherited `PMOS_*` variable is cleared. `setup.install`
and `setup.copy` read from `$FX`.

### Golden

One JSON file per case, in `modes/<mode>/evals/` or `evals/workflows/`:

```json
{
  "kind": "golden",
  "name": "plan a sprint with reduced availability",
  "covers": ["mode:pm/sprint-planning"],
  "failure": false,
  "envelope": {"verb": "plan", "mode": "pm/sprint-planning", "inputs": {"sprint": "2026-S22", "project": "STK"},
               "acceptance": ["committed points within capacity"], "risk": "high", "approval": "before_execute"},
  "fixtures": {"backlog.json": "packs/pm/modes/sprint-planning/evals/fixtures/backlog.json"},
  "gates": ["Approve the ranking as it is."],
  "expect": ["committed points <= capacity.py committed_points"]
}
```

`envelope.mode` is one of the pack's own modes (a workflow case: usually the router); `fixtures`
values are inline data or paths inside the pack; `gates` answer the mode's gates in order.

### Results (eval-result@1)

`pmos eval --json` prints [`eval-result@1`](../../contracts/eval-result.schema.json): per case the
pack, kind, covers, result (`pass`, `fail`, `error`, or `skipped` for a golden case that was only
rendered), the first failing expectation, seconds and, for golden runs, usd; and per pack (and in
total) the counts by kind.

Write expectations on **key words**, not sentences: `output: '(?i)\bcalls?\b'`, not the full error.
Never hard-code a task id or date; capture it.

### Fixtures

- `fixtures/packs/`: small packs, each meeting the coverage rule unless it exists to break it. `gtm` (depends `pm@^0.2`; router `gtm/launch-pack` calls `pm/prd`
  and `pm/release-notes`; `gtm/brief` runs under `pm/doc-writer`), `typed` (doc_ref inputs and
  outputs), `assemble` (`merge_child_actions`), `star` (`calls: ["*"]`), `loop` (calls itself),
  `bare` (bare exports, no SKILL names), `orphan` (an uncalled internal mode), `badtype` (type
  typos), `x-uncovered` (a router, a script and an action handler with only a happy-path golden
  case; `fixtures/patches/x-uncovered/` adds the missing cases), and `x-forge`, `x-cos`,
  `x-staking`, `x-noevals` (admission must refuse them).
- `fixtures/bin/`: helpers. `mkresult.py` writes and submits a result; `advance.py` takes a task
  through review and approval; `verdicts.py` builds per-line verdicts; `yset.py` edits YAML/JSON;
  `mktext.py` writes a component file of N words; `section.py`, `once.py`, `before.py`, `legend_check.py`, `unused_roles.py`,
  `cli_help_check.py`, `grants_claim_check.py`; and `fake_runner.py` / `fake_grader.py` stand in
  for `eval.command` and `eval.grader_command`. The helpers detect which contract the tree has
  (see the end of INTERFACES.md), so one owner's change doesn't break another owner's cases.

## Core's groups

95 cases: 84 conformance, 11 regression.

| Group | Cases | Regression | Covers |
| --- | --- | --- | --- |
| modularity | 26 | 5 | modularity 1–8, 10 (every "accepted", "created", "applied", "not detected" and "shown as" row of the boundary table); composability 1, 6, 9 (parent state) |
| composability | 12 | 4 | composability 2, 3, 4, 5, 7 |
| performance | 15 | 0 | performance 1–9 |
| clarity | 13 | 2 | clarity 1–9, plus the false doc claims the reviews found |
| eval-standard | 10 | 0 | request:eval@1 — the schema, the coverage rule, the sandbox, the runner, CoS/hub docs, forge skeletons, `pmos path` |
| effort | 5 | 0 | request:effort — resolution and risk scaling, risk-scaled review, schemas and defaults, renders, `task list`/`stats` |
| dispatch | 2 | 0 | request:dispatch — resolution, schemas, renders, COS.md |
| tightness | 7 | 0 | request:tightness — `pmos lint` (budgets, mode structure, filler, cite don't copy, sentence length), where it runs, `core:tight-instructions` |
| cos-thread | 5 | 0 | request:cos-thread — background long commands, the inline limit rendered from pm-os.yaml, the eval estimate, `lock_cos`, `cos-turn` and stats |

Baseline on core 0.2.0 (2026-10-24): all 55 review conformance cases failed and all 11 regression
cases passed. The eval-standard, effort and dispatch cases all failed before core 0.3.0; the
tightness and cos-thread cases all failed before core 0.3.1.

## Judgment-only (scored by `forge/review-framework`, no conformance case)

- clarity 2: a single "how to write a reference" table in the README.
- clarity 4: "phase 0" defined in one clause where it is first used.
- clarity 6: grant enforcement explained once in the README; the CoS command map in one place.
- clarity 9: the docs index separating current docs from history (superseded proposal, v0.1 PDF).
- performance 3: the harness or runner (not the Worker) writing `usage`.
- performance 6/7: "gate 1 was approved" checked from task history; a PM-approved router plan
  standing in for sprint-planning's gate 1. (Review depth scaled by risk is now code: the effort cases.)
- modularity 3: the Worker's write tools limited to `outputs/` where the harness supports it.
- composability 9: skills cited only in SKILL.md prose aren't visibility-checked; routers can't
  plan across packs.

## Not covered (deferred)

Per [`findings/README.md`](findings/README.md), these get no failing case in this round:

- splitting `pmos.py` into an importable library (modularity 9);
- declarative `playbook.yaml` composition (composability 8);
- installing two versions of one pack side by side (composability 3, long-term part);
- moving todos into a pack of its own (modularity 11);
- real agent identity for `--by`, so a Worker can't review or approve its own task (modularity 3,
  needs the DBOS process split).

# Framework evals

Evals for pm-os itself, built from the four framework reviews in [`findings/`](findings/README.md).

- **Layer 1, conformance (this folder):** deterministic cases, no model. Each describes the
  behaviour a finding asks for, so it fails until the fix lands. Regression cases (`regression: true`)
  cover what the reviewers confirmed works, and must always pass.
- **Layer 2, judgment:** the `forge/review-framework` mode re-runs a review on demand. It runs
  these cases first, then judges what code can't, against the original review question.

New interfaces the fixes implement are specified in [`INTERFACES.md`](INTERFACES.md).

## Run

```bash
python scripts/pmos.py eval --framework                       # all four reviews
python scripts/pmos.py eval --framework modularity            # one review (or several)
python scripts/pmos.py eval --framework --case 'approval-*'   # cases matching a glob
python scripts/pmos.py eval --framework --json                # the JSON summary on stdout
python scripts/framework_eval.py modularity --keep            # keep each case's temp copy to debug it
```

The table shows case, finding, result and the first failing expectation. A JSON summary goes to
`build/framework-evals/latest.json`, and the exit code is non-zero if any case fails.
`scripts/framework_eval.py` also takes `--root DIR` (test another tree with these cases),
`--out FILE` and `--jobs N`.

To re-run a whole review, with judgment, ask the CoS for one, or create the task directly:
`python scripts/pmos.py task new --mode forge/review-framework --verb review --inputs '{"aspect": "modularity"}'`.

## How a case runs

Each case gets a fresh temporary copy of the repo, without `.git`, `build/`, `state/tasks/`,
`traces/`, `outputs/` and `context/todos.yaml`. Setup runs, then the steps run in order as
`bash -c` with cwd = the copy, and each step's expectations are checked before the next one runs.
The case stops at its first failing expectation.

## Case format

One YAML file per case in `<review>/`:

```yaml
name: child-outside-calls-refused     # unique; also the file name
finding: modularity#1                 # <review>#<issue number> in findings/<review>.md (#good = a confirmed strength)
owner: modularity                     # the review whose fix agent owns it (= the folder)
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
expectations. Steps also get `$PMOS` (`python scripts/pmos.py`), `$FORGE`, `$TODOS`, `$PY` and
`$FX` (`evals/framework/fixtures`). Every inherited `PMOS_*` variable is cleared.

Write expectations on **key words**, not sentences: `output: '(?i)\bcalls?\b'`, not the full error.
Never hard-code a task id or date; capture it.

### Fixtures

- `fixtures/packs/`: small packs. `gtm` (depends `pm@^0.2`; router `gtm/launch-pack` calls `pm/prd`
  and `pm/release-notes`; `gtm/brief` runs under `pm/doc-writer`), `typed` (doc_ref inputs and
  outputs), `assemble` (`merge_child_actions`), `star` (`calls: ["*"]`), `loop` (calls itself),
  `bare` (bare exports, no SKILL names), `orphan` (an uncalled internal mode), `badtype` (type
  typos), and `x-forge`, `x-cos`, `x-staking`, `x-noevals` (admission must refuse them).
- `fixtures/bin/`: helpers. `mkresult.py` writes and submits a result; `advance.py` takes a task
  through review and approval; `verdicts.py` builds per-line verdicts; `yset.py` edits YAML/JSON;
  `section.py`, `once.py`, `before.py`, `legend_check.py`, `unused_roles.py`,
  `cli_help_check.py`, `grants_claim_check.py`; and `fake_runner.py` / `fake_grader.py` stand in
  for `eval.command` and `eval.grader_command`. The helpers detect which contract the tree has
  (see the end of INTERFACES.md), so one owner's change doesn't break another owner's cases.

## Coverage

66 cases: 55 conformance, 11 regression.

| Owner | Cases | Regression | Findings covered |
| --- | --- | --- | --- |
| modularity | 26 | 5 | modularity 1–8, 10 (every "accepted", "created", "applied", "not detected" and "shown as" row of the boundary table); composability 1, 6, 9 (parent state) |
| composability | 12 | 4 | composability 2, 3, 4, 5, 7 |
| performance | 15 | 0 | performance 1–9 |
| clarity | 13 | 2 | clarity 1–9, plus the false doc claims the reviews found |

Baseline on core 0.2.0 (2026-10-24): all 55 conformance cases fail and all 11 regression cases pass.

## Judgment-only (scored by `forge/review-framework`, no conformance case)

- clarity 2: a single "how to write a reference" table in the README.
- clarity 4: "phase 0" defined in one clause where it is first used.
- clarity 6: grant enforcement explained once in the README; the CoS command map in one place.
- clarity 9: the docs index separating current docs from history (superseded proposal, v0.1 PDF).
- performance 3: the harness or runner (not the Worker) writing `usage`.
- performance 6/7: "gate 1 was approved" checked from task history; a PM-approved router plan
  standing in for sprint-planning's gate 1; review depth scaled by risk.
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

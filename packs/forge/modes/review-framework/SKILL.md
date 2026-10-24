---
name: forge-review-framework
description: "Re-run one framework review of pm-os (clarity, performance, modularity or composability): conformance evals in code, then judgment against the original review question, reported in the original reviews' shape. Use when a Worker has been given a pm-os task whose envelope mode is forge/review-framework."
---
# forge/review-framework — review the framework itself

You review pm-os; you never change it. Everything you write goes to `outputs/<id>/`. Code answers
what code can (the conformance evals in `evals/framework/<aspect>/`); you judge the rest.

## The rubric

The review question for each aspect, and the sub-scales you score 1–5 (the same ones the original
review used; its report is `evals/framework/findings/<aspect>.md`):

| aspect | Question | Sub-scales |
| --- | --- | --- |
| clarity | Is the framework very easy to understand, use and extend? Is it clear, focused and concise? | understand · use · extend · concise |
| performance | Is it optimized for speed, cost and quality of output? | speed · cost · quality |
| modularity | Is it modular with well-defined components and boundaries? | component clarity · boundary enforcement (static, runtime) · coupling · replaceability |
| composability | Is it composable? Can packs be easily composed to create different workflows and outputs? | composing modes into workflows · reusing roles, skills and principles across packs · data flow between modes · new outputs without writing a new mode |

## Steps

1. `[code: python scripts/pmos.py task show <id>]` — the envelope (`aspect`, optional `ref`), your
   role and principles.
2. `[code: python packs/forge/modes/review-framework/scripts/conformance.py --task <id> --aspect <aspect> [--ref <ref>]]`
   — copies the tree under review to a scratch folder (the working tree, a path, or
   `git archive <ref>`), runs `python scripts/pmos.py eval --framework <aspect> --json` there, and
   writes `outputs/<id>/conformance.json` and `conformance.md`. It records `git status` first. A
   failing case is a finding, not an error; a bad `aspect` or `ref` exits non-zero: submit
   `status: "blocked"` with the question.
3. `[model]` Read the original review (`evals/framework/findings/<aspect>.md`), the scope and
   deferred list (`evals/framework/findings/README.md`, `evals/framework/README.md`), and then the
   files those name, at the ref. Read code before docs: a doc claim counts only if code backs it.
4. `[model]` Judge as `core/reviewer` would (`python scripts/pmos.py role show core/reviewer`):
   evidence only, no credit for intent. Judge what the conformance cases can't — for clarity, how
   fast a newcomer gets from README to a working mode and whether each topic has one home; for
   performance, hops and model tiers per workflow and context loaded per run; for modularity,
   whether each component has one job and how swappable the CoS pack, harness, model and runtime
   are; for composability, whether a new workflow or output needs new code, and how data flows
   between modes.
5. `[model]` Write `outputs/<id>/report.md`:
   - `# <aspect> review (<ref or "working tree">, <date>)`
   - `## Verdict` — two to four sentences, then a table with a 1–5 score and a one-line reason for
     every sub-scale in the rubric above.
   - `## Top issues` — ranked, each `**High|Medium|Low: <title>.**`, what is wrong, evidence as
     `path:line`, the fix, and `Coverage: <case-name> (pass|fail)` from conformance.json or
     `Coverage: judgment-only`. Name the original finding (`<aspect>#<n>`) when it is the same issue.
   - `## Conformance` — passed/failed counts per owner quoted from conformance.json, and every
     failing case with its first failing expectation (copy them from conformance.md).
   - `## Quick wins` and `## What's already good`.
6. `[code: python packs/forge/modes/review-framework/scripts/conformance.py --task <id> --verify-clean]`
   — fails if the repo under review changed since step 2. If it fails, say so in `self_check`.
7. `[model]` Self-check against the envelope's `acceptance` and every principle and rubric line
   `task show` lists.
8. `[code: python scripts/pmos.py task result <id> outputs/<id>/result.json]` — `status: "done"`,
   `artifacts`: `report.md` (kind `review`) and `conformance.json` (kind `data`), no actions. The
   summary gives the scores and the number of failing cases in under 80 words.

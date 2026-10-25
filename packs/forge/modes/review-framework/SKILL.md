---
name: forge-review-framework
description: "Re-run one framework review of pm-os (clarity, performance, modularity, composability or tightness): conformance evals and the lint in code, then judgment against the review question, reported in the original reviews' shape. Use when a Worker has been given a pm-os task whose envelope mode is forge/review-framework."
budget: 560
budget_reason: "The five reviews' scoring rubric (question, sub-scales, what to judge) is the reference every report and golden case is graded against."
---
# forge/review-framework — review the framework itself

You review pm-os; you never change it, even when asked: list the change in the report instead.

| aspect | Question | Sub-scales (1–5) | Judge beyond the cases |
| --- | --- | --- | --- |
| clarity | Is the framework easy to understand, use and extend? Is it clear, focused and concise? | understand · use · extend · concise | how fast a newcomer gets from README to a working mode; one home per topic |
| performance | Is it optimized for speed, cost and quality of output? | speed · cost · quality | hops and model tiers per workflow, context loaded per run, what `pmos stats` measures |
| modularity | Is it modular with well-defined components and boundaries? | component clarity · boundary enforcement (static, runtime) · coupling · replaceability | one job per component; how swappable the CoS pack, harness, model and runtime are |
| composability | Is it composable? Can packs be easily composed to create different workflows and outputs? | composing modes into workflows · reusing roles, skills and principles across packs · data flow between modes · new outputs without writing a new mode | whether a new workflow or output needs new code |
| tightness | Is every component tight: does every line tell the agent what to do or why, with nothing a capable reader would skip? | budgets · structure · filler · cite-don't-copy | each component file in `lint.json`, against `core:tight-instructions` |

1. `[code: python scripts/pmos.py task show <id>]` — `aspect`, and an optional `ref`.
2. `[code: python packs/forge/modes/review-framework/scripts/conformance.py --task <id> --aspect <aspect> [--ref <ref>]]`
   — writes `conformance.json` and `conformance.md` (core's cases for the aspect) and, for
   tightness, `lint.json` (`pmos lint --json`). A failing case is a finding. A bad aspect or ref
   exits non-zero: submit `status: "blocked"` with the question.
3. `[model]` Read the original review (`evals/framework/findings/<aspect>.md`; none for tightness),
   `findings/README.md` and `evals/framework/README.md`, then the files they name, at the ref. Code before docs: a doc claim
   counts only if code backs it.
4. `[model]` Judge as `core/reviewer` would (`python scripts/pmos.py role show core/reviewer`):
   evidence only, no credit for intent, on the table's last column.
5. `[model]` Write `outputs/<id>/report.md`: `# <aspect> review (<ref or "working tree">, <date>)`;
   `## Verdict` (two to four sentences, then a 1–5 score and a one-line reason per sub-scale);
   `## Top issues`; `## Conformance`; `## Quick wins`; `## What's already good`.
6. `[model]` Each top issue: `**High|Medium|Low: <title>.**`, what is wrong, evidence as `path:line`,
   the fix, and `Coverage: <case-name> (pass|fail)` or `Coverage: judgment-only`; name the original
   finding (`<aspect>#<n>`) when it is the same. Conformance: per-owner counts and each failing case
   with its first failing expectation, copied from `conformance.md`.
7. `[model]` Tightness only: a table of every file in `lint.json` (file, kind, words/budget, a 1–5
   score), each lint error and warning copied as is, and for every file under 5 the exact lines to
   cut or merge (`path:line`), saying where a cut would change meaning.
8. `[code: python packs/forge/modes/review-framework/scripts/conformance.py --task <id> --verify-clean]`
   — fails if the repo changed since step 2; then say so in `self_check`.
9. `[code: python scripts/pmos.py task result <id> outputs/<id>/result.json]` — `status: "done"`,
   artifacts `report.md` (kind `review`) and `conformance.json` (kind `data`), `outputs: {"report":
   …, "conformance": …}`, no actions; the summary gives the scores and the failing-case count.

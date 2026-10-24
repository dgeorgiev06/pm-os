# Quality: how work is judged

This is the one place that explains review. Every task is reviewed against three layers, in this
order. `pmos task show <id> --for-review` prints all of them for the Reviewer as a checklist.

1. **Core principles** (`skills/principles/`, `always: true`) — apply to every task in every pack:
   grounded, no unapproved side effects, answers the envelope, honest self-check, usable summary.
2. **Cited principles** — the ones the mode and the role list under `principles:`. Each principle
   has a one-line `check` the Reviewer scores, and a short body the Worker reads as guidance, so
   producer and reviewer judge against the same words.
3. **Rubric lines** — specific to one mode or role (`rubric:` in `mode.yaml` / `roles.yaml`).
   Prefer a principle when a rule applies to more than one mode.

The PM's `instructions`, when the envelope has them, add one more checklist line.

**The pass rule.** The Reviewer, in a fresh context that never sees the producer's reasoning,
records a pass/fail verdict with a note for every checklist line, plus an overall score from 0 to
5. `pmos` computes the outcome: the task passes when every core principle passes and the score is
at least 4. A pass goes to `done` or `awaiting_approval` (as the envelope's approval says); a fail
goes to `revise`, up to `max_revisions`, then `failed`.

## Improvement

Traces, review scores and your edits feed a weekly improvement loop: it clusters failing traces by
mode, workflow and role; an Improver proposes a patch (principle, skill, rubric, routing or tier
change, or a local override on a third-party mode); the patch merges only if it improves that
mode's golden evals without regressing others, and you approve the PR.

Fix the **highest layer** that solves the problem: one better principle improves every mode and
role that cites it.

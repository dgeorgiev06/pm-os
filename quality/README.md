# Quality: how work is judged

This is the one place that explains review. A task's checklist has four kinds of line, in this
order; `pmos task show <id> --for-review` prints it for the Reviewer, `--checklist` as JSON.

1. **Core principles** (`skills/principles/`, `always: true`), kind `core`: grounded, no unapproved
   side effects, answers the envelope, honest self-check, usable summary. They apply to every task.
2. **Must lines**, kind `must`: the mode's `done.must` (text lines `must-N`, and `{principle: <ref>}`
   lines with the principle's id), the task's `--acceptance` lines (`task-N`), and, when the PM gave
   instructions, `pm-instructions` with their text attached.
3. **Code lines**, kind `code`: the `{code: "<command>"}` lines of `done.must` (`code-N`). pmos runs
   them at `task result`, so they arrive **settled**: the Reviewer gives them no verdict.
4. **Should lines**, kind `should`: `done.should` (`should-N`), the principles the mode and role cite
   under `principles:` that aren't musts, and the role's `rubric:` in `roles.yaml` (`role-rubric-N`).

Each principle has a one-line `check` the Reviewer judges and a short body the Worker reads, so
producer and reviewer use the same words. A principle is advisory (a should line) until a mode's
`done.must` cites it. Prefer a principle when a rule applies to more than one mode.

**The pass rule.** pmos computes it: every core and must line holds, and the score, 5 × the share of
should lines that hold (5 with none), is at least 4. A pass goes to `done` or `awaiting_approval` (as
the envelope's approval says); a fail goes to `revise`, up to `max_revisions`, then `failed`.

## How a review is recorded

- **Code checks run first**, before any Reviewer is spent: `task result` refuses a result that
  doesn't match the schema, a summary over 80 words, or usage over the task's budget; then it runs
  the mode's `done.must` `code:` lines (repo root, `defaults.code_timeout_seconds`, output kept).
  Any failure sends the task straight to `revise` with the failing ids and their output.
- **Per-line verdicts.** The Reviewer, in a fresh context that never sees the producer's reasoning,
  records `{id, pass, evidence, fix}` for every line that isn't settled: `evidence` says where in the
  artifact (section, heading, line), `fix` (on a failed line) what must change. It runs
  `pmos task review <id> --verdicts FILE` (or `-` for stdin); pmos refuses a missing line, missing
  evidence or a failed line without a fix, and stores the lines in the task's `result.review`. The
  producer's `result.json` is never modified, so a resubmit after `revise` works.
- **The revision brief.** On `revise`, `task show` lists exactly the failed line ids and their fix
  first, before the rest of the brief.
- **One review per piece of work.** A child task whose approval rolls up to its parent (approval
  `none` under a gated parent, or `approval_from` set) goes from its result straight to `done` once
  its code lines pass; its other lines join the parent's checklist, ids prefixed with the child's.
- **Two counters.** `revisions` counts failed reviews and failed code lines (a task fails after
  `max_revisions`); `change_requests` counts the PM's "change X" after review and doesn't use up that
  budget.
- `pmos stats` reports, per mode, the first-pass review rate and how often the PM asked for changes
  after approval was requested.

## Improvement

Traces, review scores and your edits feed a weekly improvement loop: it clusters failing traces by
mode, workflow and role; an Improver proposes a patch (principle, skill, done line, routing or tier
change, or a local override on a third-party mode); the patch merges only if it improves that
mode's golden evals without regressing others, and you approve the PR.

Fix the **highest layer** that solves the problem: one better principle improves every mode and
role that cites it.

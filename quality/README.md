# Quality: how work is judged

Every task is reviewed against three layers, in this order. `pmos task show <id> --for-review`
prints all of them for the Reviewer.

1. **Core principles** (`skills/principles/`, `always: true`) — apply to every task in every pack:
   grounded, no unapproved side effects, answers the envelope, honest self-check, usable summary.
   A task fails review if any of these fail.
2. **Cited principles** — the ones the mode and the role list under `principles:`. Each principle
   has a one-line `check` the Reviewer scores, and a short body the Worker reads as guidance, so
   producer and reviewer judge against the same words.
3. **Rubric lines** — specific to one mode or role (`rubric:` in `mode.yaml` / `roles.yaml`).
   Prefer a principle when a rule applies to more than one mode.

Improvements go to the highest layer that fixes the problem: a better principle improves every
mode and role that cites it.

## How a review is recorded

- **Code checks run first**, before any Reviewer is spent: `task result` refuses a result that
  doesn't match the schema, a summary over 80 words, or usage over the task's budget, and modes run
  their own checks as `[code]` steps (`check_prd.py`, `check_plan.py`).
- **Per-line verdicts.** Each checklist line has an id (`core:grounded`, `pm:plan-to-capacity`,
  `mode-rubric-1`, `role-rubric-2`, `pm-instructions`); `pmos task show <id> --checklist` prints them
  as JSON. The Reviewer gives every line a pass or fail with a note and an overall score 0–5:
  `pmos task review <id> --verdicts FILE` (or `-` for stdin). pmos refuses incomplete verdicts,
  computes the pass (every core line holds and the score is 4 or more), and stores the lines in the
  task's `result.review`. The producer's `result.json` is never modified, so a resubmit after
  `revise` works.
- **One review per piece of work.** A child task whose approval rolls up to its parent (approval
  `none` under a gated parent) goes from its result straight to `done`; its work is reviewed inside
  the parent's review.
- **Two counters.** `revisions` counts failed reviews (a task fails after `max_revisions`);
  `change_requests` counts the PM's "change X" after review and doesn't use up that budget.
- `pmos stats` reports, per mode, the first-pass review rate and how often the PM asked for changes
  after approval was requested.

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

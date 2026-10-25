---
name: core-infra-self-check
description: Check a pm-os work product against its definition of done before submitting. Use as the last step before submitting any pm-os result.
---
# Self-check

Before submitting, go through three lists and record each item in `self_check`:

1. The mode's `done.must` lines and the task's own must lines (`task show` prints them); run each
   code line yourself, since pmos runs it again at `task result`.
2. The mode's `done.should` lines.
3. The role's `rubric` in `roles.yaml` (should lines too).

For each item: `met: true|false` and, when false or borderline, a one-line `note`.
If any item is unmet and you can fix it, fix it and re-check. If you can't, keep `met: false`
and say why — the Reviewer will see it either way, and an honest miss beats a hidden one.

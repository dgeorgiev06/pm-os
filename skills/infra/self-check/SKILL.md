---
name: infra-self-check
description: Check a pm-os work product against its acceptance criteria and rubrics before submitting. Use as the last step before submitting any pm-os result.
---
# Self-check

Before submitting, go through three lists and record each item in `self_check`:

1. The envelope's `acceptance` list.
2. The role's `rubric` in `roles.yaml`.
3. The mode's `rubric` in its `mode.yaml`.

For each item: `met: true|false` and, when false or borderline, a one-line `note`.
If any item is unmet and you can fix it, fix it and re-check. If you can't, keep `met: false`
and say why — the Reviewer will see it either way, and an honest miss beats a hidden one.

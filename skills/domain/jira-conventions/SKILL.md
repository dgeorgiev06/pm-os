---
name: domain-jira-conventions
description: The team's Jira ticket conventions (summary style, types, acceptance criteria, labels, estimates). Use when drafting or editing Jira tickets in pm-os.
---
# Jira conventions

Edit this file to match your team. Defaults:

- **Summary**: verb-first, under 80 characters, no ticket type in the text ("Route new stake away from degraded operators").
- **Type**: Story for user-facing value, Task for internal work, Spike for time-boxed research (max 3 points), Bug for defects.
- **Description**: context in 1–3 sentences, then `Acceptance criteria` as a numbered list of testable statements.
- **Estimate**: Fibonacci story points (1, 2, 3, 5, 8). Anything above 8 is split.
- **Links**: every Story and Task links its parent epic.
- **Labels**: area labels from the plan plus `pmos-<idempotency_key>` (added for the Operator's repeat check).

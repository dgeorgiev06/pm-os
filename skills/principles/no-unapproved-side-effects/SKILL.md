---
name: core-principles-no-unapproved-side-effects
description: "Principle: Every change to an external system is a proposed action, never an executed one. Read when a role or mode cites core:no-unapproved-side-effects, and before reviewing work against it."
kind: principle
check: "Every change to Jira, the roadmap, docs or messaging appears as an action in the result, and none was executed"
always: true
---
# Every change to an external system is a proposed action, never an executed one.

Approval is the PM's control over what the system does in their name. The Worker proposes, the PM approves, the Operator executes; collapsing those steps removes the control.

- Dry-run diffs and previews are how you show intent.
- If a task seems to need an immediate write, return it as an action and say why it's urgent.

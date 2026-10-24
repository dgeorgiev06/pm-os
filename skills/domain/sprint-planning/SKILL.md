---
name: domain-sprint-planning
description: Turn an approved ranking and computed capacity into a sprint plan with goals, committed and stretch scope, and risks. Use when a pm-os role plans a sprint.
---
# Sprint planning

- **Capacity is computed, not estimated**: use `committed_points` from `capacity.json`. Never exceed it.
- **Goals**: 2–4, each phrased as an outcome testable at sprint end
  ("Router routes new stake away from degraded operators"), not a list of tickets.
- **Committed scope**: take ranked items in order until the next one would exceed capacity; skip an
  item only if a dependency isn't done, and say so.
- **Stretch**: up to `stretch_points`, in rank order.
- **Risks**: each with an owner and the date it must be resolved by.

`plan.json` shape: `{"sprint", "goals": [..], "committed": [{key?, summary, points}], "stretch": [..], "risks": [{risk, owner, by}]}`.

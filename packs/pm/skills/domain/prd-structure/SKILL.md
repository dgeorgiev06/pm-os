---
description: How to write a strong PRD — the evidence, the requirements and the metrics. Use when drafting or revising a PRD in pm-os; the outline itself is the standard pm:standards/prd, which `task show` prints.
---
# Writing a PRD well

The outline and its checked rules live in `pm:standards/prd`: `task show` prints them and
`check_doc.py` checks them. This skill is the judgment no checker makes.

## Evidence

- Open the problem with what was observed (a ticket, a call note, a number) and its ref.
- Keep what a customer said apart from what you infer; label each inference as an assumption.
- Say what waiting costs: a commitment, a deadline, revenue at risk.

## Requirements

- One behaviour per requirement; split any line joined by "and".
- Cover the unhappy path: an operator degrades, data arrives late, an approval is refused.
- State what must be true, not how to build it, unless the constraint is real (a regulator, a contract).
- Each one meets `pm:testable-requirements`; customer claims meet `pm:cite-customer-claims`.

## Metrics

- Measure the outcome the problem names (stake routed, reports accepted), not activity.
- Pick a target someone could argue with, and say where the number is read (a dashboard, a report).
- Prefer one metric that moves to five that are tracked.

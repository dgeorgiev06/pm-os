# pm-os docs

The repo's [README](../README.md) is the entry point: how to use and extend pm-os. These docs go
deeper.

| Doc | What's in it |
| --- | --- |
| [implementation-spec.md](implementation-spec.md) | **The active plan**: the locked model, the gaps against `main`, and Stage A/B/C with exit criteria |
| [target-model.md](target-model.md) | What the spec builds, drawn: the three axes, the layered map, one task end to end, and `pm/prd` rewritten against the target |
| [architecture.md](architecture.md) | The design: principles, the four agents, who owns which state, the improvement loop, cost/speed/accuracy levers |
| [decisions.md](decisions.md) | Every design decision so far and why |
| [diagrams.md](diagrams.md) | Phase 0 (built today) and the final durable-runtime design, as diagrams |
| [walkthrough-sprint-planning.md](walkthrough-sprint-planning.md) | Planning a sprint step by step: what you say, which agents run, how state moves |
| [phase-0-and-build-plan.md](phase-0-and-build-plan.md) | How phase 0 runs (what `pmos` is, how a request runs, its limits) and the phases after it |
| [routing-and-delegation.md](routing-and-delegation.md) | Who picks the mode, who names a new mode, managing todos, delegating a todo with instructions |
| [runtime-dbos.md](runtime-dbos.md) | The durable runtime for phase 3: why DBOS, how workflows are defined, how pm-os maps onto it |
| [../quality/README.md](../quality/README.md) | How work is reviewed and improved |

History (superseded, kept for reference): the original
[v0.1 design doc](history/PM-Agent-OS-Architecture.pdf), and the
[todo-plan proposal](history/todo-plan-proposal.md) that `cos/todos` replaced.

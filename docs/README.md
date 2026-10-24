# pm-os docs

| Doc | What's in it |
| --- | --- |
| [architecture.md](architecture.md) | The current design: diagram, principles, building blocks, agents, state ownership, packs and registration, quality loop, cost/speed/accuracy levers |
| [decisions.md](decisions.md) | Every design decision so far and why |
| [walkthrough-sprint-planning.md](walkthrough-sprint-planning.md) | Planning a sprint step by step: what you say, which agents run, how state moves |
| [phase-0-and-build-plan.md](phase-0-and-build-plan.md) | How phase 0 runs (what `pmos` is, when the CoS calls it, its limits) and the phases after it |
| [routing-and-delegation.md](routing-and-delegation.md) | Who picks the mode, who names a new mode, and how todos become agent tasks |
| [runtime-dbos.md](runtime-dbos.md) | The durable runtime for phase 3: why DBOS, how workflows are defined, how pm-os maps onto it |
| [proposals/todo-plan.md](proposals/todo-plan.md) | Proposed `pm/todo-plan` mode with delegation (not built yet) |
| [PM-Agent-OS-Architecture.pdf](PM-Agent-OS-Architecture.pdf) | The original v0.1 design doc, kept for history |

The repo's [README](../README.md) covers how to use the framework; `quality/README.md` covers how
work is reviewed; `examples/dbos/` has the durable-runtime examples.

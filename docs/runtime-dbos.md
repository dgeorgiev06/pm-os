# Durable runtime: DBOS (phase 3)

When the CoS thread must stay free during long work, approvals wait for days, or work must run on
a schedule, the workflow manager moves from the `pmos` CLI to a durable workflow engine. The
contract doesn't change; packs, modes, roles, principles and the CoS carry over.

## Recommendation

**DBOS by default; Temporal if pm-os becomes a multi-team platform.**

- **DBOS is a library, not a server.** Workflows are rows in Postgres; app processes dequeue and
  checkpoint each step back to Postgres. The only infrastructure is Postgres, which also makes it
  easy to self-host.
- **Task state stays queryable with SQL**, so the status board and traces read straight from it.
- **It handles agent loops**: completed steps (including model calls) replay from checkpoints on
  recovery, so a crashed run resumes from the first unfinished step instead of re-paying for it.
- **Temporal** is the established enterprise option (long waits, many teams and languages) at the
  cost of running a server cluster or using Temporal Cloud. Use it if your org already runs it.
- **Inngest** if you want zero ops and a managed service; **Restate** is a strong design but younger
  and BSL-licensed.

## How DBOS workflows are defined

- `@DBOS.workflow()` marks a workflow; `@DBOS.step()` marks each non-deterministic part (model
  calls, tool calls, Jira reads). If a workflow is interrupted, it recovers from the last
  completed step.
- `Queue(name, concurrency=…)` and `queue.enqueue(fn, …)` run work in the background and return a
  handle; enqueued work supports timeouts, deduplication ids and priority.
- `DBOS.recv()` pauses a workflow until a message arrives (an approval); `DBOS.send()` delivers it.
- `DBOS.set_event()` publishes progress that a client reads with `get_event()`.
- Child workflows: a parent enqueues children and waits on their handles. Scheduled workflows run
  on cron.

## How pm-os maps onto it

| pm-os | DBOS |
| --- | --- |
| `pmos` state machine | workflow state in Postgres |
| One generic `run_envelope` | a workflow every envelope runs: resolve mode → validate inputs → run mode workflow → review → approval wait → execute → finalize |
| A mode's workflow | a workflow registered from the pack at worker startup |
| Agents | queues: `worker`, `review`, `batch`, and `operator` (consumed only by the process holding write credentials) |
| `waiting` on children | child workflows enqueued with the parent's budget |
| Gates (`blocked`, `awaiting_approval`) | `DBOS.recv("approval", timeout)`; the CoS sends your answer |
| Envelope id | workflow id, so a duplicated envelope never runs twice |
| Status board | `set_event` progress + SQL over workflow tables |
| Scheduled check-ins | scheduled workflows |

Processes: the CoS in its own process (so long work never stalls your thread), a worker pool
running many tasks concurrently, and the Operator in a separate process that holds the write
credentials, so the permission line is enforced by the OS.

Three rules to bake in:

1. **Workflow bodies must be deterministic.** Every model call, tool call, clock read or random value
   goes in a step; model non-determinism is fine because the step's output is checkpointed.
2. **Mode discovery happens at boot.** A newly installed mode goes live on a rolling worker restart.
3. **Keep old mode versions until their runs drain.** In-flight workflows replay against the code
   that started them, including ones waiting days on an approval.

## Examples

`examples/dbos/sprint_workflows.py` has two mode workflows:

- `plan_next_sprint` — reads systems of record, prioritizes (gate 1), runs the roadmap diff and the
  sprint plan in parallel as child envelopes, drafts tickets, asks for one approval (gate 2), has
  the Operator execute, and starts the tracker keyed by sprint id.
- `track_sprint` — a daily durable loop: reads Jira, computes burndown and risks in code, spends a
  model call only on new risks (proposing fixes through the CoS, never writing), and at sprint end
  writes a review and records actual velocity for the next plan.

## Sources

- [DBOS Python programming guide](https://docs.dbos.dev/python/programming-guide)
- [DBOS queue tutorial](https://docs.dbos.dev/python/tutorials/queue-tutorial)
- [DBOS queue worker example](https://docs.dbos.dev/python/examples/queue-worker)
- [DBOS with the Vercel AI SDK](https://docs.dbos.dev/integrations/vercel-ai)
- [Durable AI agents on Postgres with DBOS](https://dev.to/mr_manushukla/durable-ai-agents-without-temporal-exactly-once-workflows-on-postgres-with-dbos-2026-5a6n)
- [Inngest: durable workflows and comparison with Temporal](https://www.inngest.com/docs/durable-execution/durable-workflows.md)
- [Temporal vs Inngest vs Restate vs DBOS for agent runs](https://www.beri.net/article/temporal-vs-inngest-vs-restate-vs-dbos-durable-execution-agent-cost)

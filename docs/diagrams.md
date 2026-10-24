# Diagrams: phase 0 and the final design

## Phase 0 — skills in a harness (what's built)

One agent session plus this repo. The CoS is the main session; the other three agents are
subagents; `pmos` is a script; state is files. Nothing runs unless the session is active.

```mermaid
flowchart TB
  PM([You<br/>terminal · desktop · mobile]) <-->|chat| COS

  subgraph HARNESS["Agent harness session (e.g. Claude Code)"]
    COS["Chief of Staff — main session<br/>AGENTS.md via CLAUDE.md"]
    W["worker subagent<br/>thinking roles · no writes"]
    R["reviewer subagent<br/>fresh context"]
    O["operator subagent<br/>only writer"]
    COS -->|"invoke with task id"| W
    COS -->|"invoke with task id"| R
    COS -->|"after your yes"| O
  end

  subgraph REPO["Repo on disk"]
    PMOS["scripts/pmos.py<br/>state machine · registry · validation"]
    TODOS["packs/cos/scripts/todos.py"]
    PACKS["packs/: cos · pm · forge<br/>modes · roles · skills · principles"]
    STATE[("state/tasks · status.md · catalog.md<br/>traces/*.jsonl · outputs/")]
    TODOF[("context/todos.yaml")]
    PMOS --> STATE
    TODOS --> TODOF
  end

  COS -->|"bash: task new / approve / move"| PMOS
  COS -->|"exact todo edits"| TODOS
  W -->|"task show / result"| PMOS
  R -->|"task review"| PMOS
  O -->|"action run"| PMOS
  W -. "reads skills (rendered to .claude/skills)" .-> PACKS
  W -. "read-only MCP" .-> MCPR["Jira · docs · calendar"]
  O -->|"approved actions"| MCPW["Jira · docs · Slack"]
  PMOS -->|"pack action handlers<br/>(forge sync · todos apply)"| REPO
  REPO -->|"git push · PRs"| GH["GitHub dgeorgiev06/pm-os"]
```

Limits: your thread may wait while a foreground subagent runs; no schedules unless the harness has
them; no pushed events, so a new session catches up from `state/status.md`.

## Final design — durable runtime (phase 3)

The CoS becomes a service you reach from Slack or your phone; DBOS on Postgres runs every
envelope as a durable workflow; agents become processes split by credentials; the improvement loop
runs on a schedule. Packs, modes, roles, principles and contracts are unchanged.

```mermaid
flowchart TB
  PM([You]) <-->|"Slack · Claude mobile"| COS

  COS["Chief of Staff service<br/>own process · AGENTS.md from the cos pack<br/>replies in seconds, never waits"]

  subgraph WM["Workflow manager — DBOS on Postgres"]
    RUN["run_envelope workflow<br/>resolve → validate → run mode → review<br/>→ approval wait → execute → finalize"]
    Q["queues: worker · review · batch · operator"]
    WAIT["durable waits<br/>approvals can take days"]
    SCHED["scheduled workflows<br/>sprint tracker · Monday health · weekly loop"]
    REG["registry + catalog<br/>packs.yaml · admission · grants"]
    RUN --> Q
    RUN --> WAIT
  end

  PG[("Postgres<br/>workflow state · traces · status board")]
  WM --- PG

  COS -->|"start envelope · send approval"| WM
  WM -->|"events: needs approval · done · blocked"| COS

  subgraph POOL["Worker pool process"]
    W["Worker runs<br/>role from roles.yaml · tier → model id<br/>prompt caching"]
    R["Reviewer runs<br/>fresh context · principles checklist"]
  end
  OP["Operator process<br/>sole holder of write credentials"]

  Q --> POOL
  Q --> OP

  subgraph PACKS["Packs (git sources: local · org · third-party)"]
    P1["cos · pm · forge"]
    P2["third-party packs"]
  end
  REG --> PACKS
  POOL -. "modes · skills · principles" .-> PACKS

  subgraph GW["Tool gateway — MCP"]
    T1["Jira · docs · calendar · GitHub · Slack<br/>grants · dry-run · audit log"]
  end
  POOL -->|"read-only"| GW
  OP -->|"approved writes"| GW

  CTX[("Context store<br/>product · customers · decisions · todos")]
  POOL -. reads .-> CTX

  subgraph LOOP["Improvement loop (batch, weekly)"]
    A["Analyst: cluster failing traces"] --> I["Improver: patch principle · skill · rubric · routing"]
    I --> E["Eval gate: golden + regression tasks"]
    E -->|"PR via forge"| PRR["Your approval"]
  end
  PG --> LOOP
  PRR -. merged .-> PACKS

  MODELS["Model providers<br/>small · mid · top via tier map"]
  POOL --> MODELS
  COS --> MODELS
```

What changes from phase 0: your thread never waits, approvals and the sprint tracker survive
restarts and run unattended, the CoS is told about events instead of polling, and the permission
line is enforced by process boundaries as well as tool lists.

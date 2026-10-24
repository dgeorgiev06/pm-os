"""
Example mode workflows for the PM Agent OS on DBOS.

  Mode 1  core/sprint-planning  - prioritize next sprint, update roadmap, plan work, create Jira tickets
  Mode 2  core/sprint-tracking  - track a running sprint until it closes, then feed learnings back

Framework helpers (provided by the pm-os runtime, not by DBOS). Each one is a DBOS step
or enqueues a child workflow, so every workflow body below stays deterministic:

  read(env, tool, query)              step: read-only tool call through the gateway
  role_call(env, role, task, schema)  step: one Worker run under a role, structured output
  call_mode(env, mode, verb, inputs)  enqueues a child envelope (run_envelope), returns a handle
  await_decision(env, kind, payload)  posts an approval request to the CoS, waits on DBOS.recv
  execute(env, actions)               enqueues actions on the Operator queue, waits for the result
  notify_cos(env, digest, level)      step: posts a digest or decision request to your thread
  record_decision(env, text)          step: appends to decisions.log
  write_context(env, key, value)      step: updates the context store
  now(), seconds_until(ts)            steps: clock reads (never read the clock in a workflow body)

--- modes/core/sprint-planning/mode.yaml ---------------------------------------------------
name: core/sprint-planning
version: 1.0.0
contract: task@1
summary: Prioritize the next sprint, update the roadmap, plan the work, create Jira tickets
accepts: { sprint: string, team: string, goals_hint: string? }
returns: { sprint_plan: doc_ref, roadmap_diff: diff_ref, tickets: list }
workflows: [plan_next_sprint]
calls: [core/roadmap@^1, core/sprint@^1, core/jira@^1, core/sprint-tracking@^1]
grants: { jira: read, roadmap: read, calendar: read }   # writes only via the Operator
approval: before_execute

--- modes/core/sprint-tracking/mode.yaml ---------------------------------------------------
name: core/sprint-tracking
version: 1.0.0
contract: task@1
summary: Track a running sprint daily; flag risks; close it out with a review
accepts: { sprint: string, team: string, plan: sprint_plan }
returns: { review: doc_ref }
workflows: [track_sprint]
grants: { jira: read }   # read-only; fixes are proposed to the CoS as new envelopes
approval: none
"""

from dbos import DBOS

from pm_os import (
    call_mode, await_decision, execute, notify_cos, now, read, record_decision,
    role_call, schemas, seconds_until, write_context,
)

MAX_REVISIONS = 2


# =============================================================================
# Mode 1: plan the next sprint
# =============================================================================
@DBOS.workflow()
def plan_next_sprint(env: dict) -> dict:
    sprint = env["inputs"]["sprint"]
    team = env["inputs"]["team"]

    # 1. Facts from systems of record, read fresh (cheap reads, no model calls)
    backlog = read(env, "jira", {"jql": f"project = {team} AND status = Backlog ORDER BY rank"})
    roadmap = read(env, "roadmap", {"file": "roadmap.yaml"})
    velocity = read(env, "jira", {"report": "velocity", "team": team, "last_n": 3})
    capacity = read(env, "calendar", {"team": team, "sprint": sprint})
    decisions = read(env, "context", {"file": "decisions.log", "since_days": 30})

    # 2. Prioritize (top-tier role). Gate 1: you approve or redirect before
    #    anything more expensive runs. No writes happen at this gate.
    feedback = None
    for _ in range(MAX_REVISIONS + 1):
        ranking = role_call(
            env, "roadmap-strategist",
            task={"backlog": backlog, "roadmap": roadmap, "decisions": decisions,
                  "hint": env["inputs"].get("goals_hint"), "feedback": feedback},
            schema=schemas.PriorityRanking,   # ranked items + score + one-line rationale each
        )
        decision = await_decision(env, "priorities", ranking)
        if decision["verdict"] == "approve":
            break
        feedback = decision["notes"]
    else:
        return {"status": "blocked", "reason": "priorities not agreed"}
    record_decision(env, f"{sprint} priorities: {ranking['summary']}")

    # 3. Fan out: the roadmap diff and the sprint plan only need the ranking,
    #    so they run in parallel as child envelopes (each reviewed on its own)
    roadmap_h = call_mode(env, "core/roadmap@^1", "draft",
                          {"ranking": ranking, "roadmap": roadmap, "want": "diff"})
    plan_h = call_mode(env, "core/sprint@^1", "plan",
                       {"ranking": ranking, "velocity": velocity,
                        "capacity": capacity, "sprint": sprint})
    roadmap_diff = roadmap_h.get_result()
    plan = plan_h.get_result()

    # 4. Ticket drafts need the plan. The gateway runs them as a dry-run and
    #    dedupes against existing tickets, so this returns a diff, not writes.
    tickets = call_mode(env, "core/jira@^1", "draft",
                        {"plan": plan, "backlog": backlog, "sprint": sprint}).get_result()

    # 5. Gate 2: one approval for everything that will change a system.
    #    This wait can last days and survives restarts.
    decision = await_decision(env, "execute", {
        "plan": plan["summary"],
        "roadmap_diff": roadmap_diff["diff"],
        "ticket_diff": tickets["diff"],
    })
    if decision["verdict"] != "approve":
        return {"status": "blocked", "reason": decision.get("notes")}

    # 6. Writes go through the Operator only; idempotency key = envelope id + action index
    applied = execute(env, roadmap_diff["actions"] + tickets["actions"])

    # 7. Start tracking. Fire-and-forget; the workflow id dedupes it, so a
    #    retry of this step never starts a second tracker for the same sprint.
    call_mode(env, "core/sprint-tracking@^1", "analyze",
              {"sprint": sprint, "team": team, "plan": plan},
              workflow_id=f"track-{team}-{sprint}")

    notify_cos(env, level="done", digest={
        "sprint": sprint,
        "goals": plan["goals"],
        "tickets_created": len(applied["created"]),
        "roadmap_changes": len(roadmap_diff["actions"]),
    })
    return {"status": "done", "sprint_plan": plan["doc_ref"],
            "roadmap_diff": roadmap_diff["ref"], "tickets": applied["created"]}


# =============================================================================
# Mode 2: track the sprint while it runs
# =============================================================================
CHECK_EVERY_SECONDS = 24 * 3600   # daily; the CoS can wake it early with "refresh"


def sprint_metrics(snapshot: dict, plan: dict) -> dict:
    """Pure code, no model: burndown vs ideal, scope added/removed, blocked tickets
    and their age, goals at risk. Deterministic, so it can run in the workflow body."""
    ...


@DBOS.workflow()
def track_sprint(env: dict) -> dict:
    sprint = env["inputs"]["sprint"]
    team = env["inputs"]["team"]
    plan = env["inputs"]["plan"]
    already_flagged: set[str] = set()

    while now() < plan["end_ts"]:
        snapshot = read(env, "jira", {"sprint": sprint,
                                      "fields": ["status", "points", "assignee", "updated", "flagged"]})
        metrics = sprint_metrics(snapshot, plan)
        DBOS.set_event("progress", metrics)      # the CoS status board reads this

        # Spend a model call only when something new went wrong
        new_risks = [r for r in metrics["risks"] if r["id"] not in already_flagged]
        if new_risks:
            response = role_call(env, "sprint-planner",
                                 task={"metrics": metrics, "risks": new_risks, "plan": plan},
                                 schema=schemas.RiskResponse)   # cause + proposed actions
            # Proposed fixes (drop a story, swap an owner) go to you via the CoS;
            # if approved, the CoS sends a new core/jira envelope. The tracker never writes.
            notify_cos(env, digest=response,
                       level="needs_decision" if response["actions"] else "info")
            already_flagged |= {r["id"] for r in new_risks}

        # Durable, interruptible sleep: wakes at the next check or on a message
        msg = DBOS.recv("tracker", timeout_seconds=seconds_until(now() + CHECK_EVERY_SECONDS))
        if msg == "stop":
            return {"status": "stopped"}

    # Sprint closed: review it and feed actual velocity into the next planning run
    final = read(env, "jira", {"sprint": sprint, "report": "sprint_report"})
    review = role_call(env, "sprint-planner", task={"plan": plan, "final": final},
                       schema=schemas.SprintReview)   # goals hit/missed, carry-over, causes
    record_decision(env, f"{sprint} closed: {review['summary']}")
    write_context(env, "velocity", {"team": team, "sprint": sprint,
                                    "completed_points": final["completed_points"]})
    notify_cos(env, digest=review, level="done")
    return {"status": "done", "review": review["doc_ref"]}

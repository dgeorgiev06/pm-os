# Performance review findings (2026-10-24)

**Verdict.** The design is lean and well thought through on paper, but several of the levers in the architecture doc's "Cost, speed and accuracy levers" table aren't implemented in phase 0. Per-role tiers are ignored by the Claude Code render, budgets and usage aren't enforced or measured, review isn't scaled by risk, and evals can't be graded. The context loaded per run is small. The extra cost comes from hops and from one model tier for everything. **Speed 2/5, cost 3/5, quality 3/5.**

**Top issues**

1. **High: role tiers never reach the model.** `render_claude_code` in `scripts/pmos.py` writes one `worker.md` with `model: sonnet`, and `role.tier` is never used. So `roadmap-strategist` and `tech-architect` (top) and `jira-curator` and `todo-planner` (small) all run on mid. The headline cost and quality lever does nothing in phase 0, and the walkthrough's claim that the ranking used the top tier is false. Fix: render one worker subagent per tier (`worker-small`, `worker-mid`, `worker-top`), and have `task show` print `delegate to: worker-<tier>`. The CoS then delegates to that one.

2. **High: the CoS manual never dispatches child tasks or re-queued parents.** `COS.md` step 7 only covers results that land. When T-101 creates T-102 and moves to `waiting`, nothing tells the CoS to delegate T-102, or to re-delegate T-101 once pmos re-queues it. Router children with no dependencies between them are also never run in parallel. Sprint planning and the router can stall. Fix: after every subagent returns, run `pmos task list --state queued` and delegate each queued task, in parallel in the background where there are no dependencies.

3. **High: none of the four metrics is actually captured.**
   - Cost per task type: `usage` is optional and self-reported by the Worker, which can't know its own token count. `max_usd` and `max_minutes` are stored but never checked.
   - Latency and first-pass review rate: derivable from trace timestamps and review events, but there's no command for them.
   - Edit rate: not captured at all.

   Fix: let the harness or runner write `usage` (a Claude Code SubagentStop hook, or the generic runtime). Add `pmos stats`: per mode, cost, p50/p90 run time, first-pass rate, and revise-after-approval rate as the edit-rate proxy. Refuse `task result` when the budget is exceeded.

4. **High: evals aren't gradable, and they collide.**
   - The runner's output goes to `output.md`, and `grader.md` is never run or scored.
   - Only `state/` and `traces/` are isolated. `outputs/` isn't, so every case gets id `T-<today>-001` and writes to the same real `outputs/` folder.
   - The sprint-planning case tells the agent to stop at gate 1, but its `expect` list checks stage C results.

   Fix: add `PMOS_OUTPUTS_DIR`, a grader step (reviewer tier) that writes `score.json`, scripted gate answers so multi-stage modes run to the end, and a pass-rate summary.

5. **Medium: pass/fail is the Reviewer's word, not checked.** `cmd_task_review` accepts `--passed true --score 1` with a failing core principle. Per-line checklist results aren't stored. Fix: require per-line verdicts (JSON), and have pmos compute pass as "all core lines hold and score ≥ 4".

6. **Medium: some checks are trivially satisfied or cheap to do in code.**
   - `acceptance` defaults to `[]` (the CoS never passes `--acceptance`), so `honest-self-check` checks nothing.
   - Code can check: summary under 80 words with a link (`task result`), committed points ≤ `capacity.json` (`plan-to-capacity`), and "gate 1 was approved" from task history.

   Fix: let modes declare default `acceptance`, and run these checks in pmos before any Reviewer is spent.

7. **Medium: too many hops and double reviews.** Sprint planning takes 7 subagent runs (4 Worker, 2 Reviewer, 1 Operator), 2 PM gates, and about 6 CoS turns:
   - Stage C is a whole mid-tier run just to concatenate actions.
   - The tickets get reviewed twice (once on T-102, again inside T-101).
   - Through the router, sprint planning is always high-risk, so the router's plan gate always fires, then gate 1 fires as well.

   Fix: do stage C in pmos code (auto-assemble the child's actions when the parent re-queues). Skip review for children with `approval: none` whose parent is reviewed. Let a gate the PM already approved for the plan stand in for gate 1.

8. **Low: `revisions` is shared between review failures and PM "change X" requests.** `task move revise` and a failed review both increment it, so PM edits use up the `max_revisions: 2` budget. Fix: keep two counters.

9. **Low: caching order is volatile-first.** `task show` prints the envelope (id, timestamps) before the stable mode, role and principles. Fix: stable sections first, envelope and history last.

**Quick wins**
- Render a worker per tier and print `delegate to:` in `task show` (fixes issue 1).
- Add a "dispatch queued tasks, in background" rule to `COS.md` (fixes issue 2).
- pmos computes review pass; summary length is checked in code (issues 5 and 6).
- Add `PMOS_OUTPUTS_DIR` plus a grader run in `pmos eval` (issue 4).
- Add `pmos stats` over the traces (issue 3).
- Promote sprint-planning's `[candidate-code]` steps 1–2 (JQL and velocity read) and add a `check_plan.py` capacity check. These run on every sprint and are pure rules.

**Token load (measured).** A sprint-planning Worker run loads about 5k tokens of framework text:

| What | Size |
| --- | --- |
| `task show` | 2.7 KB |
| `worker.md` | 2.6 KB |
| `SKILL.md` | 3.8 KB |
| 7 principles | ~4.7 KB |
| 3 skills | ~3 KB |
| context files | ~0.5 KB |
| `role show` | ~1 KB |

The Reviewer loads about 4 KB plus the artifacts. The CoS carries `AGENTS.md` (6.8 KB) on every turn. None of this is a problem. Jira payloads and the number of hops are what drive cost.

**What's already good**
- Thin orchestration: the CoS passes only a task id, and `usable-summary` keeps it from reading artifacts.
- Strict state: illegal transitions are refused, results are validated against the schema, and approval is pinned to a hash of the actions.
- The codify ladder is real: `capacity.py`, `dedupe.py`, `check_prd.py` and `group_tickets.py` work, and the Worker is told to run `[code]` steps rather than reason through them.
- Fresh-context review against the same check lines the Worker read. Routers are only for goal-level asks, which saves a hop on direct jobs.

My test copy is at `/tmp/claude-0/-home-claude/3edf8ea7-aa78-5b04-80a2-d4a23af1ce20/scratchpad/review-perf`. The original repo at `/home/claude/pm-os-git` was not modified.

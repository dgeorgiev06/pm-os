# Composability review findings (2026-10-24)

**Verdict.** pm-os composes well structurally but poorly at the data level. Packs, `depends`/`exports`, visibility rules, depth limits and cycle checks are enforced in code. Building a three-pack workflow (gtm on top of pm, plus core) took about 10 minutes and installed on the first try. What pmos actually guarantees is: create children, wait, wake the parent. Everything that flows between modes is prose in SKILL.md: which child output feeds which input, how results and actions are merged, what happens when a child fails. `calls` and version pins are only checked when a pack is installed, never when a task runs. Scores:
- **Composing modes into workflows: 3/5**
- **Reusing roles, skills and principles across packs: 4/5**
- **Data flow between modes: 2/5**
- **New outputs without writing a new mode: 2/5**

**Top issues**

1. **High: `calls` is not enforced when a child task is created.** `cmd_task_new` → `resolve_mode(from_pack=parent.pack)` checks only pack visibility. A gtm/launch-pack parent (calls: prd, release-notes) created pm/jira-tickets and pm/sprint-planning children without error. docs/routing-and-delegation.md §3 says "limited to the modes listed in its `calls`, which `pmos` enforces", which is false. **Fix (small):** when there is a parent, require `split_ref(args.mode)[0]` to match one of the parent mode's `calls` and resolve it with that pin. Allow an explicit `calls: ["*"]` or `dynamic: true` for routers.

2. **High: a failed dependency deadlocks the whole workflow.** In my run, B depended on A; A failed, so B stayed `queued` forever (`move running` is refused) and the parent stayed `waiting` forever. `maybe_wake_parent` needs every child to be terminal, and nothing cascades the failure. **Fix (small):** when a task fails, move its queued dependents to `failed` (note: "dependency X failed"), or wake the parent with a partial result.

3. **High: upgrading a dependency silently breaks dependents and in-flight tasks.** Upgrading pm 0.2.0 → 0.3.0 succeeded, after which `validate` failed on gtm (`depends on pm@^0.2`, `calls pm/prd@^0.2`). gtm could still start pm/prd children, which got 0.3.0 because of issue 1. The existing task T-…-002 (pm/prd@0.2.0) then failed `task show` with "no installed mode matches". `check_pack` in `cmd_pack_add` checks only the pack being added. Pins can't pick a version anyway: only one copy of each pack is installed. **Fix:** at admission, also run `check_pack` on every pack that depends on the upgraded one and refuse (or require `--force`). In `task show`, fall back to the stored `mode_dir`. Longer term, allow side-by-side versions.

4. **High: `accepts`/`returns` types are mostly decorative.** `TYPE_CHECKS` has no `doc_ref` or `diff_ref`, and unknown types pass. `prd: [1,2]` was accepted for `doc_ref`, and the typos `dco_ref` and `whatever` passed `validate`. `returns` is never read by pmos. A result can omit the declared `prd` and carry `kind: "banana"`; it was accepted. **Fix (medium):** a closed type vocabulary in mode.schema.json; `doc_ref` checked as an existing path or `scheme:` ref; a `result.outputs: {name: ref}` map validated against `returns` in `cmd_task_result`.

5. **High: there is no wiring from one child's output to another child's input.** The only way is to wait for child A, read its result.json, then create child B; or guess `outputs/<A>/prd.md` from A's SKILL.md conventions. `depends_on` orders tasks but can't bind data. Child results are exposed only as a `result_path` line in `task show`. **Fix (medium):** with issue 4's `outputs` map, let inputs reference `{"$from": "T-…-002", "output": "prd"}`, resolved when the child moves to running.

6. **Medium: merging and approvals are unsafe conventions.** sprint-planning gives its child `--approval none` and copies the child's actions into its own result, by prose. `--approval` and `--risk` overrides are unrestricted even at the top level: pm/sprint-planning (before_execute, high) was created with `none`. A task with `approval: none` and actions went to `done` with the actions unexecuted and nothing flagged. **Fix (small):** forbid weakening approval unless the parent's approval is at least as strict; flag results whose actions will never run; add a `merge_child_actions` flag or a pmos helper.

7. **Medium: PM instructions and budgets don't flow down.** Children don't inherit `instructions` (C1's envelope had none). Each child's budget is capped at the parent's total; spending isn't summed, despite "children draw down the parent's". **Fix (small):** inherit instructions, and sum children's `usage.usd` against the parent's budget.

8. **Medium: no declarative composition.** The `workflow` envelope field is stored and never used. There is no retry or fallback (a failed child just wakes the parent), and no conditional branching other than model judgment. Every new output means a new mode with mode.yaml, SKILL.md, a golden eval and grant approval. **Fix (refactor):** a `playbook.yaml` mode kind: steps with mode, inputs (using `$from` refs), `depends_on`, `when`, `retry`, `on_fail`, and an assemble step. pmos expands it into child tasks, with no SKILL.md needed.

9. **Low: other gaps.**
   - A child can be created under a parent that is `queued` or `done` (T-…-015, T-…-017).
   - Skills cited only in SKILL.md prose aren't visibility-checked, since modes have no `skills` field.
   - Routers can't discover other packs' modes: pm/router → gtm was correctly refused unless gtm is in `depends`, so cross-pack goals must go through the CoS.

**What I built and ran.** I built `gtm` 0.1.0 by hand: `depends: [pm@^0.2]`, a router `gtm/launch-pack` that calls pm/prd and pm/release-notes, a role `launch-lead` reusing `pm:domain/prd-structure` and `pm:cite-customer-claims`, and a principle `one-page`. `pack add --approve-grants` passed on the first try.
- **Worked:**
  - `--parent` children.
  - `depends_on` ordering (the dependent child was refused until its dependency finished).
  - Auto-requeue of the parent once both children were terminal, including when one failed.
  - The cycle check refused gtm→gtm.
  - forge→gtm was refused without `depends`.
  - An unexported `pm:product/staking-prd` was refused.
  - `default_role: pm/doc-writer` resolved pm's principles correctly.
  - `pack remove pm` was blocked by the dependent gtm.
- **Didn't work:** issues 1–7 above, each reproduced in the scratch copy at /tmp/claude-0/-home-claude/3edf8ea7-aa78-5b04-80a2-d4a23af1ce20/scratchpad/review-compose. Nothing in /home/claude/pm-os-git was modified.

**What's already good**
- Visibility checks are consistent across modes, roles, skills and principles, at admission and at `task new` (`visibility_error`). The error messages say exactly what to add.
- Packs are truly installable: admission, grant approval, dependency-aware removal, and the catalog and AGENTS.md regenerated automatically.
- The child, waiting and requeue state machine is simple, deterministic and traced. Depth and cycle limits work.
- Principles reuse well: the core, mode and role layers merge with the right owner resolution, and `task show --for-review` gives producer and reviewer the same check lines.

# Clarity review findings (2026-10-24)

**Verdict.** pm-os holds together better than most agent frameworks. The core idea is easy to grasp: a thin CoS hands off work, a deterministic `pmos` owns task state, four agents are split by permissions, and the Worker reads the same principles the Reviewer scores. The CLI is solid. The quick start runs without errors, and error messages tell you how to fix things (`unknown input(s) ['goals']; pm/prd accepts [...]`, `mode 'pm/weekly-update' is internal ... (not in its exports)`, and the grant error that names the exact `pack add --upgrade --approve-grants` command). What holds it back is how much a newcomer has to take in, and some old explanations that no longer match the code. The README uses around 20 terms (envelope, grant, export, depends, verb, tier, rubric, golden eval, action, gate, admission, registry, adapter, codify ladder…). Several appear before they're defined, and the same material is explained in three or four places, not always the same way. **Scores: understand 3 · use 4 · extend 3 · concise 3.**

**Top issues**

1. **High: old names still in the files a newcomer reads.**
   - `docs/routing-and-delegation.md:13` says "The `pm/todo-plan` Worker proposes a mode per todo; you approve the list". Lines 51–66 of the same doc say delegation happens only when the PM directs it. Line 28 also uses `pm/todo-plan`.
   - `contracts/task.schema.json:33` still has the example "core/prd or core/prd@^1".
   - `examples/dbos/sprint_workflows.py:4-33,89-117` uses `core/sprint-planning`, `modes/core/...`, `core/roadmap`, `core/jira` and `core/sprint`, none of which exist.
   - `agents/reviewer.md:3` says it reviews "against the baseline, mode and role rubrics"; there is no baseline rubric any more.
   - **Fix:** rewrite the routing doc's item 2 to the `cos/todos` and directed-delegation model, change the schema example to `pm/prd@^0.2`, rename the modes in the DBOS example to `pm/*`, and change the reviewer line to "core principles, cited principles and rubrics".
2. **High: six different ways to write a reference.**
   - Modes and roles use `pm/prd` and `pm/doc-writer`; skills and principles use `pm:domain/prd-structure` and `pm:plan-to-capacity`.
   - SKILL.md frontmatter uses `pm-prd`, `pm-principles-plan-to-capacity` and `core-infra-envelope-io`.
   - In `pack.yaml`, `exports.modes` takes prefixed names (`pm/prd`) but roles, skills and principles take bare ones.
   - **Fix:** at least put one "how to write a reference" table in the README (the `forge:authoring` table is good; promote it). Better: accept bare names in `exports.modes`, and generate or relax the SKILL `name` check so authors never type it.
3. **Medium: the README never explains the `pmos` shorthand.** It switches between `pmos ...` and `python scripts/pmos.py ...`, and a newcomer who types `pmos validate` gets "command not found". **Fix:** one line in the quick start: `alias pmos="python scripts/pmos.py"`, or a console-script entry.
4. **Medium: terms used before they're defined.** "Phase 0" (line 5), "grants" (line 14), "envelope" (line 84; never defined in the README), and "pstack" (lines 78 and 117, plus architecture and decisions; this is outside context to a reader). **Fix:** add Envelope, Grant and Action rows to the Building blocks table, define phase 0 in one clause, and drop the pstack mentions.
5. **Medium: adding a mode by hand is underspecified, and the docs disagree on versions.**
   - README lines 182–188 don't list the required `mode.yaml` fields (schema requires name, version, contract, summary, accepts, returns, default_role, approval). They also give no template and no golden-eval shape. I had to copy `prd/`.
   - `validate` passes a mode that isn't exported, and the problem only shows at `task new`.
   - The README says widening a grant "means bumping the pack's version", but `pack add --upgrade --approve-grants` worked with no bump (it printed `upgraded pm 0.2.0`).
   - `forge:authoring` says to bump on any change; the README says nothing about bumping.
   - **Fix:** a 6-line "copy `packs/pm/modes/prd` and edit" recipe, or a `pmos new mode PACK/NAME` scaffold reusing `forge.py`'s skeleton. Have `validate` warn about unexported modes. Pick one version rule and make pmos enforce it.
6. **Medium: the same things are explained in several places.**
   - The three review layers are in the README, `architecture.md` and `quality/README.md`.
   - The Building blocks table is in both the README and `architecture.md`.
   - Grant enforcement is explained twice in the README (lines 100–114) and again in architecture and authoring.
   - The CoS command map is in both COS.md and `phase-0-and-build-plan.md`.
   - The step-tag legend is copied into every SKILL.md, worded differently each time.
   - **Fix:** keep one canonical home for each, and leave a link elsewhere.
7. **Low: `--verb` adds little.** Every mode declares exactly one verb, yet `--verb` is required and errors if wrong. **Fix:** default it to the mode's only verb.
8. **Low: CLI help is bare.** `task new --help` lists 17 flags; only two have descriptions, and `--workflow` isn't documented anywhere.
9. **Low: noise in the pm pack and docs index.**
   - `tech-architect`, `qa-planner` and `research-analyst` in `packs/pm/roles.yaml` aren't used anywhere.
   - README lines 199–200 say "three steps are already codified", but `group_tickets.py`, `todos.py` and `forge.py` also exist.
   - The docs index lists a superseded proposal and the v0.1 PDF next to current docs.

**Quick wins**
- Add `alias pmos=...` to the quick start, plus a step 4: "say 'draft a PRD for X' to the CoS".
- Fix the four stale references from issue 1.
- Add Envelope, Grant and Action rows to the Building blocks table, and a reference-syntax table.
- Replace the ASCII "How work flows" diagram with the clearer mermaid state diagram from `architecture.md`.
- Move `proposals/` and the PDF to `docs/history/`, and delete the unused pm roles.
- Make the README's "Mode" recipe say: copy `packs/pm/modes/prd`, the required fields are..., add it to `exports.modes`, run `validate`, then run `catalog`.

**What's already good**
- **pmos errors teach the system.** I hit wrong verbs, misspelled inputs, an unexported mode, a wrong SKILL name, missing evals and an over-wide grant. Each error said what was wrong and the exact command to fix it.
- **`task show` is an excellent single brief.** It gives the envelope, the role, the core, mode and role principles with their file paths, and a review checklist that matches what the Worker was told.
- **The mode files are tight and readable.** `mode.yaml` is a clear typed contract, and SKILL.md steps are short, tagged and concrete (`prd` is a good model to copy).
- **The safety rules are stated once and enforced in code**, not just in prompts: only the Operator writes, approval is a task state, grants are checked at `validate` and `task new`, and installing a pack is the PM's step.

I ran everything in a scratch copy at `/tmp/claude-0/-home-claude/3edf8ea7-aa78-5b04-80a2-d4a23af1ce20/scratchpad/review-clarity`. `/home/claude/pm-os-git` was not modified.

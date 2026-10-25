# Known issues: framework-fixes (PR #6)



Full list of open issues from the final review round, as they appear in the PR description. Each entry gives where it was observed, why it matters and the planned fix. Severity groups follow the PR.



Framework work since the last merged PR (#5). Core is at 0.6.0. This PR is **not ready to merge**: it's opened to review the work and the known issues below. Items marked **blocking** are the ones the reviews reproduced as breaking a rule the README says is enforced.

- **Conformance evals (eval@1).** Every pack's features are tested. `pmos eval --all --kind conformance` runs every pack, and a coverage rule fails admission when a feature has no case.
- **Definition of done.** Each mode has a `done:` block. Code lines run before any Reviewer; verdicts need evidence; `fix:` is required on failed lines; pmos computes the pass.
- **Effort and dispatch.** Set per role, agent, mode or task, adjusted by risk. Reviewers run high, implementers medium. Background dispatch by default.
- **Document standards.** `pm:standards/prd` is the single source for PRD structure. A generic `check_doc.py` enforces it. Product overlays come from data (`--product` or `context/product.md`).
- **Tightness lint.** Word budgets, filler list, cite-don't-copy, structure checks, for every component.
- **Send receipts.** An external send isn't `done` until the handler returns a receipt.
- **Notifications.** `cos/notify` renders messages from templates in code and proposes one `comms.send` per recipient. `release-comms` builds release notifications from `pm/release-notes`.
- **Channels.** A channel is a folder with `channel.yaml` and a send handler. Adding one doesn't change `cos`.
- **CoS thread protection.** Long commands go to the background, inline answers are capped, replies are logged, and `lock_cos` is available (off by default).

## Verification

- `pmos validate`: OK
- `pmos lint`: 0 errors, 0 warnings
- `pmos eval --coverage`: no gaps
- `pmos eval --all --kind conformance`: **158 / 158** (core 120, channels 2, pm 8, forge 11, release-comms 2, cos 15)
- Four final reviews run through `forge/review-framework` at high effort: clarity, performance, modularity, composability. Their findings are in **Known issues**.

## Known issues

Each item says what was observed, where, why it matters and the planned fix. The reviewers' reports couldn't be saved as files in this harness, so the findings below are taken from their returned output, and the reproductions were run in scratch copies. Nothing tracked was changed by the reviews.

### Blocking: approval and boundaries

**1. A Worker can approve its own task.**
- *Where:* `pmos task approve --by` takes any string (`scripts/pmos.py`, around line 4097). Workers hold `shell:pmos` (`agents/worker.md`).
- *Observed:* `task approve --by worker` succeeded.
- *Why it matters:* the approval gate for external sends can be satisfied by the producer.
- *Planned fix:* refuse agent names for `--by`; take approval identity from the harness, not from free text.
- *Coverage:* judgment only. `review-cannot-be-bypassed` covers `task move`, not `approve`.

**2. Any running task can attach a child to any running parent.**
- *Where:* `cmd_task_new` checks the parent's state. `resolve_call` checks the parent's `calls` list, not the caller's.
- *Observed:* an unrelated `pm/prd` task attached a `pm/jira-tickets` child to a running sprint-planning parent.
- *Why it matters:* this breaks the `calls` boundary the composition model relies on.
- *Planned fix:* check the caller against the parent's `calls`, and refuse children from tasks that aren't the parent.
- *Coverage:* judgment only. `child-outside-calls-refused` covers a direct child only.

**3. An action with no handler can strand a task, or be closed with nothing applied.**
- *Where:* `pm/sprint-planning` proposes `roadmap.apply_diff`. No pack declares a handler, no roadmap tool is mapped, and the Operator doesn't grant one.
- *Observed:* the task stays `approved`. A bare `task move … done` succeeds, because only external sends are checked.
- *Why it matters:* a task can look finished while its change was never applied.
- *Planned fix:* at `task result`, refuse actions that have no handler or tool mapping; refuse a bare `done` on an approved task with unsent actions.
- *Coverage:* judgment only. `unrunnable-actions-flagged` covers `approval: none` only.

**4. The docs overstate what's enforced.**
- *Where:* `docs/decisions.md` #13 says grants are enforced by tool access. The render itself warns that Worker and Operator grants are not enforced.
- *Observed:* the case `grants-claim-matches-code` checks only for a phrase that was removed, so it passes without testing the claim.
- *Why it matters:* readers are told a boundary exists that the code doesn't enforce.
- *Planned fix:* correct the docs to the actual enforcement; rewrite the case to check the claim itself.

### Blocking: composition

**5. A child can take its input from its own parent, which deadlocks the pair.**
- *Where:* `check_from_refs` (around line 1919) accepts any non-failed source. A parent in `waiting` can only move to `failed` or `queued`. The cycle check walks mode names, not task ids.
- *Observed:* a `cos/notify` child of a running router, with `draft: {"$from": <router>}`, was accepted. The child can never start, and the parent can never finish.
- *Planned fix:* refuse `$from` and `depends_on` that point at an ancestor in the task chain.
- *Coverage:* judgment only.

**6. A recipe in a SKILL file names a pin and a flag its own mode refuses.**
- *Where:* `packs/release-comms/modes/release-notify/SKILL.md` says `cos/notify@^0.1`. The mode's `calls` says `^0.2`. The same step passes `--approval none`, which a router with `approval: none` isn't allowed to use.
- *Observed:* the step, run as written, is refused.
- *Planned fix:* `pmos lint` checks every `--mode` pin and `--approval` flag in a SKILL against that mode's `calls` and `approval`, or renders those lines from `mode.yaml`.
- *Coverage:* judgment only.

**7. A document reference can silently feed a text input.**
- *Where:* `scripts/pmos.py` around line 1935 allows a `doc_ref` into a `string` input.
- *Observed:* `goal: string` received `outputs/<id>/notes.md` with no error.
- *Planned fix:* remove the exception. A mode that wants a path declares a ref type.
- *Coverage:* judgment only.

**8. The channel test cases depend on each deployment's `pm-os.yaml`.**
- *Where:* `packs/channels/evals/conformance/email.yaml` and `slack.yaml` expect `not configured`. The admission sandbox copies `pm-os.yaml`, so mapping a real tool makes the case fail.
- *Observed:* mapping the email tool made the email case fail, and a later channels upgrade was refused in the sandbox.
- *Planned fix:* each case sets `channel_tools: {}` in its own sandbox config, or asserts only what holds with or without a mapping.
- *Coverage:* judgment only.

### Cost and quality (performance review)

**9. Cost isn't measured, and nothing bounds a live run.**
- *Where:* budgets are checked only at `task result`. Usage is self-reported. The result schema defines `tokens_in` and `tokens_out`, which pmos never reads.
- *Observed:* the three recorded results show `usd: 0.0`.
- *Planned fix:* take usage from the harness; record tokens as well as USD; say in the docs that cost is advisory until then.

**10. Output quality isn't checked on live runs.**
- *Where:* `eval.command` is empty in `pm-os.yaml`, so golden evals are "rendered only" and skipped. The `done` code line for review-framework checks that the repo is clean, not that the report is any good.
- *Planned fix:* set `eval.command`, run the goldens once with `eval.max_usd`, and add a structural check on reports (required sections, `path:line` per issue).

**11. `effort` is only a label on claude-code.**
- *Where:* `pm-os.yaml` sets `supports_effort: false`. `task show` still prints `effort: high`, and the agent file has no effort field.
- *Planned fix:* print "not applied" when the adapter can't set it.

### Clarity and docs

**12. The docs describe an improvement loop that isn't built.** `quality/README.md` and `docs/architecture.md` describe a weekly Analyst and Improver in the present tense. No code implements either. *Planned fix:* mark it as planned.

**13. The documented way to add a mode fails lint.** The README tells readers to copy `packs/pm/modes/prd`, which trips the near-duplicate check, and it doesn't mention `forge.py stage-mode`. *Planned fix:* point to `stage-mode`.

**14. The same explanations appear in several places,** despite `quality/README.md` calling itself the one place for review. The eval commands are repeated in the README and in `evals/framework/README.md`. *Planned fix:* one home per topic.

**15. The defaults are staking-specific.** `pm/prd`'s summary, the pm pack summary and `context/product.md` all assume staking. *Planned fix:* neutral defaults; product from config.

**16. The Evals table in the README is malformed.** It renders as an empty table with a paragraph in it. *Planned fix:* correct the table.

**17. A clarity case passes without checking anything.** `doc-claims-backed` has `|| exit 0` guards that skip its checks. *Planned fix:* remove the guards.

### Medium: modularity and composition

**18. Core names defaults for one pack.** `--by` and `--reply-to` default to `cos`. The channel format is a closed core enum, and a new harness adapter is refused. *Planned fix:* take defaults from `cos_pack`; make formats extensible.

**19. The `cos` pack is bound by name to `release-comms`.** `release-comms` depends on `cos@^0.5` and its mode hard-codes `cos/notify` and `cos:external-voice`. Renaming the CoS pack breaks three packs (`validate` catches each one). The README says the CoS can be swapped. *Planned fix:* correct the README now; config-based binding later.

**20. A new audience needs a code change, and the error for an unknown one is misleading.** The audience list is a constant in `build_actions.py`. An unknown audience is reported as a missing channel. *Planned fix:* read audiences from `context/channels.yaml`; name the bad audience in the error.

**21. An additive bump under 0.x breaks every dependent pin.** Bumping `channels` 0.1.0 to 0.2.0 made `cos`, `release-comms` and `gtm` fail until each pin was moved by hand. *Planned fix:* one upgrade step that re-pins dependents.

**22. Parent-to-child hand-offs and audiences rely on prose.** A child gets its draft as a path, not a `$from`. `pm/release-notes` uses `customers|internal`, while release-notify and cos use `internal|external`. *Planned fix:* `$from` from a child's output once it's done; one audience vocabulary.

**23. `$from` doesn't check the source's visibility, and missing optional outputs are dropped silently.** *Planned fix:* apply the visibility check to the source's mode; record dropped inputs in `inputs_resolved`.

**24. CoS routing and budget live in prose.** The release routing line is in `COS.md`, and the CoS word budget was raised to 1100 to fit it (919 words now). *Planned fix:* route from the catalog; keep only exceptions in `COS.md`.

### Medium: performance

**25. Every top-level task pays for a Reviewer run.** Only gated children skip review. *Planned fix:* skip review for low-risk, approval-none top-level tasks whose code lines pass.

**26. Sprint planning routes a top-tier step to the mid tier,** and keeps a model step for stage C, which is supposed to merge children in code. *Planned fix:* set the ranking role explicitly; move stage C into code.

## Process notes

- The reviews' queued tasks (`T-20261025-004` to `-007`) remain in local state, which is gitignored. They weren't resulted, because their final step needs a saved report.
- Forge was removed and re-added to upgrade 0.5.0 in place, since the same version can't be upgraded in place.
- Grant approvals are recorded in `state/grant-approvals.jsonl`. `comms: draft` was approved by the PM.
- The `channels-batch-wip` stash was dropped; its work is in commit `97aa022`.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

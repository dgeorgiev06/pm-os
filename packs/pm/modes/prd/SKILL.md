---
name: pm-prd
description: Draft a product requirements document (PRD) for a pm-os task whose envelope mode is pm/prd. Use when a Worker has been given such a task id.
---
# pm/prd — draft a PRD

Inputs: `goal` · `refs` (optional list) · `audience` (optional).

1. `[code: python scripts/pmos.py task show <id>]` — the envelope, role and any revise notes. On a
   revision, start from `outputs/<id>/prd.md`, address every note and skip to step 5.
2. `[model]` Read each ref fresh: Jira refs with read-only Jira tools, `doc:` refs from disk, `url:`
   refs with your fetch tool. Note facts with their ref.
3. `[model]` Outline with `pm:domain/prd-structure`; for staking products also `pm:product/staking-prd`.
4. `[model]` Draft `outputs/<id>/prd.md`. Number every requirement (R1, R2, …); cite refs inline as `[ref]`.
5. `[code: python packs/pm/modes/prd/scripts/check_prd.py outputs/<id>/prd.md]` — required sections,
   numbered requirements, no unresolved TODOs. Fix and rerun until it passes.
6. `[code: python scripts/pmos.py task result <id> outputs/<id>/result.json]` — `status: "done"`
   (publishing waits for review and approval), `artifacts: [{"kind": "doc", "ref":
   "outputs/<id>/prd.md", "title": "<PRD title>"}]`, `outputs: {"prd": "outputs/<id>/prd.md"}`, and
   `actions: []` unless the envelope asks to publish; then one `docs.publish` action
   (`idempotency_key: "<id>-publish"`, `payload: {"path": "outputs/<id>/prd.md", "destination":
   "<where>"}`, `preview: "Publish PRD '<title>' to <where>"`).

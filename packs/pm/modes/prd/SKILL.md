---
name: pm-prd
description: Draft a product requirements document (PRD) for a pm-os task whose envelope mode is pm/prd. Use when a Worker has been given such a task id.
---
# pm/prd — draft a PRD

## Inputs (from the envelope)

`goal` (required) · `refs` (optional list) · `audience` (optional).

## Steps

1. `[code: python scripts/pmos.py task show <id>]` — load the envelope, role and any revise notes.
   If this is a revision, start from `outputs/<id>/prd.md` and address every note; skip to step 5.
2. `[model]` Read each ref fresh: Jira refs with read-only Jira tools, `doc:` refs from disk,
   `url:` refs with your fetch tool. Note facts with their ref.
3. `[model]` Outline with the `pm:domain/prd-structure` skill. For staking products, also apply
   `pm:product/staking-prd`.
4. `[model]` Draft `outputs/<id>/prd.md`. Number every requirement (R1, R2, …). Cite refs inline as `[ref]`.
5. `[code: python packs/pm/modes/prd/scripts/check_prd.py outputs/<id>/prd.md]` — required sections,
   numbered requirements, no unresolved TODOs. Fix and rerun until it passes.
6. `[model]` Self-check against the envelope's `acceptance` and every principle and rubric line `task show` lists.
7. `[code: python scripts/pmos.py task result <id> outputs/<id>/result.json]` — submit a result with:
   - `status: "done"` (publishing happens only after review and approval)
   - `artifacts: [{ "kind": "doc", "ref": "outputs/<id>/prd.md", "title": "<PRD title>" }]`
   - `actions: []` unless the envelope asks to publish; then one
     `{ "system": "docs", "op": "publish", "idempotency_key": "<id>-publish", "payload": {"path": "outputs/<id>/prd.md", "destination": "<where>"}, "preview": "Publish PRD '<title>' to <where>" }`

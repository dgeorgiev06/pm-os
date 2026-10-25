# Framework review findings

Four independent reviews of pm-os, run on 2026-10-24 against core 0.2.0:
[clarity](clarity.md), [performance](performance.md) (speed, cost, quality),
[modularity](modularity.md) and [composability](composability.md).

Each finding that code can check is a conformance case in `evals/framework/<review>/`, and its `finding`
field points back here. Judgment-only findings are scored by the `forge/review-framework` mode.

## Scope of the first fix round

Fixed: every high or medium finding an eval can verify.

Deferred (recorded, not fixed yet):
- splitting `pmos.py` into an importable library (modularity 9);
- declarative `playbook.yaml` composition (composability 8);
- installing two versions of one pack side by side (composability 3, long-term part);
- moving todos into a pack of its own (modularity 11);
- real agent identity for `--by` (modularity 3, needs the DBOS process split).

## Who fixes what

Where reviews overlap, exactly one owner fixes it.

| Area | Owner | Findings |
| --- | --- | --- |
| Run-time enforcement: `calls`, parent must be running, transition ownership, approval/risk floor, actions tied to grants, approved-actions hash, artifacts under `outputs/`, forged instructions, `forge.py apply` source, core naming packs (`actions:` map in `pack.yaml`, generic `origin`), validate flags missing packs, pack scripts use pmos instead of reading state | modularity | modularity 1–8, 10; composability 1, 6, 9 (parent state) |
| Typed `accepts`/`returns`, result `outputs` map, `$from` input wiring, failure cascade, upgrade re-checks dependents, `task show` fallback, instructions and budgets flow to children | composability | composability 2–5, 7 |
| One Worker per tier and `delegate to:` line, CoS dispatch rule, budget enforcement, `pmos stats`, pmos-computed review pass, mode default acceptance, code checks (summary length, plan within capacity), stage C in code, review skip for gated children, separate revision counters, stable-first `task show`, gradable isolated evals (`PMOS_OUTPUTS_DIR`, grader, scripted gates) | performance | performance 1–9 |
| Stale names, one reference syntax (bare `exports.modes`, generated SKILL names), `pmos` alias, glossary, mode recipe, unexported-mode warning, one version rule, de-duplicated docs, `--verb` default, CLI help, unused roles, docs that state only what code enforces | clarity | clarity 1–9 |

---
name: pm-domain-prioritization
description: Rank backlog items with RICE plus explicit commitments and dependencies, and write the ranking with rationale. Use when a pm-os role must prioritize a backlog or roadmap.
---
# Prioritization

1. **Hard constraints first**, ranked above any score: contractual or regulatory commitments,
   items blocking a committed launch, security issues. Mark them `commitment`.
2. **Score the rest with RICE**: Reach (customers or accounts affected) × Impact (0.25 / 0.5 / 1 / 2 / 3)
   × Confidence (50% / 80% / 100%) ÷ Effort (points). Use the backlog's points for effort.
3. **Adjust for dependencies**: an item that unblocks others moves up to just before what it unblocks.
4. **Check against `decisions.log`**: if the ranking contradicts a recent decision, keep the ranking
   but flag the conflict in the rationale.
5. **Write it**: a table with rank, key, score (or `commitment`), and a one-line rationale naming the
   goal or customer it serves. End with a short "deliberately deferred" list and why.

Don't invent reach or impact numbers you have no basis for: use the category, and set confidence to 50%.

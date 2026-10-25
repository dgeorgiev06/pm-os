---
name: forge-principles-compose-dont-copy
description: "Principle: Reuse exported roles, skills and principles instead of copying them. Read when a role or mode cites forge:compose-dont-copy, and before reviewing work against it."
kind: principle
check: "No new skill, role or principle duplicates one an installed pack already exports; reuse is declared through depends"
---
# Reuse exported roles, skills and principles instead of copying them.

A copied rule drifts from its original, and fixes stop propagating. Citing an exported principle or skill means one improvement reaches every user of it.

- Cross-pack reuse needs the other pack in depends and the item in its exports.

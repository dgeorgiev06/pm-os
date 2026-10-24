---
name: badtype-main
description: "Fixture mode badtype/main for the framework evals. Use when a Worker has been given a pm-os task whose envelope mode is badtype/main."
---
# badtype/main

Fixture used by evals/framework. It has no real steps.

1. `[code: python scripts/pmos.py task show <id>]`
2. `[code: python scripts/pmos.py task result <id> outputs/<id>/result.json]`

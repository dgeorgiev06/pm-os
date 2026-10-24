---
name: orphan-main
description: "Fixture mode orphan/main for the framework evals. Use when a Worker has been given a pm-os task whose envelope mode is orphan/main."
---
# orphan/main

Fixture used by evals/framework. It has no real steps.

1. `[code: python scripts/pmos.py task show <id>]`
2. `[code: python scripts/pmos.py task result <id> outputs/<id>/result.json]`

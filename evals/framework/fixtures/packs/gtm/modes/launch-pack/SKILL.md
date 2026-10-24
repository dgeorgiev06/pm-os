---
name: gtm-launch-pack
description: "Fixture mode gtm/launch-pack for the framework evals. Use when a Worker has been given a pm-os task whose envelope mode is gtm/launch-pack."
---
# gtm/launch-pack

Fixture used by evals/framework. It has no real steps.

1. `[code: python scripts/pmos.py task show <id>]`
2. `[code: python scripts/pmos.py task result <id> outputs/<id>/result.json]`

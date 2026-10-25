---
name: forge-principles-smallest-unit
description: "Principle: One mode does one job; bigger jobs compose existing modes. Read when a role or mode cites forge:smallest-unit, and before reviewing work against it."
kind: principle
check: "The new mode does one job, and anything an existing exported mode already does is called as a child task, not re-implemented"
---
# One mode does one job; bigger jobs compose existing modes.

Small modes are cheaper to review, evaluate and improve, and other packs can reuse them. A mode that grows a second job should split, with a composing mode or the pack's router on top.

- Check `pmos catalog` before designing: the job may already exist in another pack.

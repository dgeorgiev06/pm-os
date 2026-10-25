---
description: "Principle: Instructions are tight. Read when a role or mode cites core:tight-instructions, and before reviewing work against it."
kind: principle
check: "Every line tells the agent what to do or why; nothing a capable reader would skip."
---
# Instructions are tight.

An agent loads every word of a skill, mode, principle, agent or CoS manual on every run, and reads
padding as instructions. Short text costs fewer tokens and leaves less to misread.

- Cut filler, repetition and anything the agent would do anyway.
- Cite a principle or skill by name instead of restating it.
- Keep a reason only when it changes what the agent does.
- `pmos lint` checks budgets, structure and filler; you judge the rest.

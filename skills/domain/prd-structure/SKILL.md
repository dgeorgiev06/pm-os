---
name: domain-prd-structure
description: Standard PRD outline and writing rules. Use when drafting or revising a PRD in pm-os.
---
# PRD structure

Use these sections, in order (check_prd.py enforces the first five headings):

1. **Problem** — who has it, evidence (cited), why now.
2. **Personas** — who uses it and what they need; for institutional products, include the compliance or risk reviewer.
3. **Requirements** — numbered R1, R2, …; each testable. Group as Must / Should / Later.
4. **Success metrics** — metric, baseline (or "to measure"), target, how it's measured.
5. **Open questions** — each with an owner.
6. **Non-goals** — what this deliberately does not cover.
7. **Risks and dependencies**.

Rules: no adjectives without a number ("fast" → "p95 under 300 ms"); every customer claim cites a ref;
mark assumptions as assumptions.

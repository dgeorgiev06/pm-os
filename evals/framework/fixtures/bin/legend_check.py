#!/usr/bin/env python3
"""Fail if mode SKILL.md files word the step-tag legend in more than one way.

The legend is the paragraph starting with "Step tags:". Zero or one distinct wording passes
(e.g. one canonical legend that every SKILL.md links to, or identical copies).
"""
import re
import sys
from pathlib import Path

wordings = {}
for f in sorted(Path("packs").glob("*/modes/*/SKILL.md")):
    text = f.read_text(encoding="utf-8")
    m = re.search(r"^Step tags:.*?(?=\n\s*\n|\Z)", text, flags=re.M | re.S)
    if m:
        # only the tag definitions count, not extra sentences after them
        legend = re.match(r"Step tags:[^.]*\.?", " ".join(m.group(0).split())).group(0)
        wordings.setdefault(legend, []).append(str(f))
for w, files in wordings.items():
    print(f"{len(files)} file(s): {w}")
sys.exit(1 if len(wordings) > 1 else 0)

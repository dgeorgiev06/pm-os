#!/usr/bin/env python3
"""Print one Markdown section (heading line matching REGEX, up to the next heading of the same or
higher level).  section.py FILE REGEX"""
import re
import sys
from pathlib import Path

lines = Path(sys.argv[1]).read_text(encoding="utf-8").splitlines()
rx = re.compile(sys.argv[2], re.I)
out, level = [], None
for line in lines:
    m = re.match(r"^(#+)\s+(.*)", line)
    if m and level is not None and len(m.group(1)) <= level:
        break
    if m and level is None and rx.search(m.group(2)):
        level = len(m.group(1))
    if level is not None:
        out.append(line)
if not out:
    sys.exit(f"no heading matching /{sys.argv[2]}/ in {sys.argv[1]}")
print("\n".join(out))

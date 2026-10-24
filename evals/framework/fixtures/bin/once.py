#!/usr/bin/env python3
"""Fail if REGEX (whitespace-insensitive) matches in more than MAX of the given files.

  once.py REGEX MAX FILE ...
"""
import re
import sys
from pathlib import Path

rx, limit, files = sys.argv[1], int(sys.argv[2]), sys.argv[3:]
hits = []
for f in files:
    p = Path(f)
    if p.exists() and re.search(rx, " ".join(p.read_text(encoding="utf-8").split()), flags=re.I):
        hits.append(f)
print(f"/{rx}/ found in {len(hits)} file(s): {', '.join(hits) or '-'}")
sys.exit(1 if len(hits) > limit else 0)

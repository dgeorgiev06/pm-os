#!/usr/bin/env python3
"""A stand-in for eval.grader_command: passes every checklist line in grader.md.

  fake_grader.py GRADER_FILE OUTPUT_FILE
"""
import json
import sys
from pathlib import Path

lines = [l[6:].strip() for l in Path(sys.argv[1]).read_text(encoding="utf-8").splitlines() if l.startswith("- [ ] ")]
print(json.dumps({"passed": True, "lines": [{"line": l, "pass": True} for l in lines]}))

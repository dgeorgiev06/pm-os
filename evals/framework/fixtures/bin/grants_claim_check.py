#!/usr/bin/env python3
"""If docs/decisions.md still says grants are "enforced at run time", the generic render must
give each role or mode its own tool/grant list (keys with a '/' in build/generic/grants.json)."""
import json
import re
import subprocess
import sys
from pathlib import Path

text = Path("docs/decisions.md").read_text(encoding="utf-8")
if not re.search(r"enforced at run[- ]time", text, flags=re.I):
    print("claim not made")
    sys.exit(0)
subprocess.run([sys.executable, "scripts/pmos.py", "render", "generic"], check=True, capture_output=True)
grants = json.loads(Path("build/generic/grants.json").read_text(encoding="utf-8"))
scoped = [k for k in grants if "/" in k]
if not scoped:
    print("docs/decisions.md says grants are enforced at run time, but tools are rendered per agent only "
          f"(grants.json keys: {sorted(grants)})")
    sys.exit(1)
print(f"per-role/mode grants rendered: {scoped[:5]}")

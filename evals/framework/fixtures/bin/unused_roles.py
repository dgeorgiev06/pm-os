#!/usr/bin/env python3
"""Fail if an installed pack defines a role that is neither exported nor used by any mode."""
import sys
from pathlib import Path

import yaml

root = Path(".")
entries = (yaml.safe_load((root / "packs.yaml").read_text(encoding="utf-8")) or {}).get("packs") or []
used = set()
pack_dirs = {}
for e in entries:
    d = root / e["path"]
    man = yaml.safe_load((d / "pack.yaml").read_text(encoding="utf-8")) or {}
    pack_dirs[man["name"]] = (d, man)
    for mf in d.glob("modes/*/mode.yaml"):
        m = yaml.safe_load(mf.read_text(encoding="utf-8")) or {}
        for r in [m.get("default_role"), *(m.get("roles") or [])]:
            if r:
                used.add(r if "/" in r else f"{man['name']}/{r}")
unused = []
for name, (d, man) in pack_dirs.items():
    rf = d / "roles.yaml"
    if not rf.exists():
        continue
    exported = set((man.get("exports") or {}).get("roles") or [])
    for rname in ((yaml.safe_load(rf.read_text(encoding="utf-8")) or {}).get("roles") or {}):
        if f"{name}/{rname}" not in used and rname not in exported:
            unused.append(f"{name}/{rname}")
if unused:
    print("roles neither exported nor used by any mode: " + ", ".join(unused))
    sys.exit(1)
print("every role is exported or used")

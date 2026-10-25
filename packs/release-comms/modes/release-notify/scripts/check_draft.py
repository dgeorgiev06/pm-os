#!/usr/bin/env python3
"""check_draft — the release-notify done check: a draft.json passes cos/notify's checks.

Usage: check_draft.py DRAFT.json. cos owns the checks (templates, fields, channels, internal-only text);
this runs cos's `build_actions.py --check` and passes its output and exit code through.
"""
import os
import subprocess
import sys
from pathlib import Path


def pm_os_root() -> Path:
    if os.environ.get("PMOS_ROOT"):
        return Path(os.environ["PMOS_ROOT"]).resolve()
    for d in Path(__file__).resolve().parents:
        if (d / "pm-os.yaml").exists():
            return d
    sys.exit("error: can't find the pm-os repo; set PMOS_ROOT")


def pack_dir(root: Path, name: str) -> Path:
    proc = subprocess.run([sys.executable, str(root / "scripts" / "pmos.py"), "pack", "path", name],
                          cwd=root, capture_output=True, text=True)
    if proc.returncode != 0:
        sys.exit(f"error: pack '{name}' is not installed; release-comms depends on it")
    return Path(proc.stdout.strip())


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: check_draft.py DRAFT.json", file=sys.stderr)
        return 2
    root = pm_os_root()
    checker = pack_dir(root, "cos") / "modes" / "notify" / "scripts" / "build_actions.py"
    return subprocess.run([sys.executable, str(checker), "--check", sys.argv[1]], cwd=root).returncode


if __name__ == "__main__":
    sys.exit(main())

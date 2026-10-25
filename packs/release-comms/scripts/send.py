#!/usr/bin/env python3
"""send — release-comms' comms.send handler (pack.yaml `actions:`).

The notify children's sends are merged into a release-notify task, and pmos runs the handler of the
task's own pack. This hands each action to cos/notify's handler, which verifies it against channels.yaml
and refuses until a comms tool is mapped. Usage: send.py ACTION.json
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


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: send.py ACTION.json", file=sys.stderr)
        return 2
    root = pm_os_root()
    proc = subprocess.run([sys.executable, str(root / "scripts" / "pmos.py"), "pack", "path", "cos"],
                          cwd=root, capture_output=True, text=True)
    if proc.returncode != 0:
        sys.exit("error: cos is not installed; release-comms depends on it")
    handler = Path(proc.stdout.strip()) / "modes" / "notify" / "scripts" / "build_actions.py"
    return subprocess.run([sys.executable, str(handler), "send", sys.argv[1]], cwd=root).returncode


if __name__ == "__main__":
    sys.exit(main())

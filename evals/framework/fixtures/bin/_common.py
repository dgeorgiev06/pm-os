"""Shared helpers for the framework-eval fixture scripts. Run from the repo copy's root."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path.cwd()


def pmos(*args: str, check: bool = False) -> subprocess.CompletedProcess:
    proc = subprocess.run([sys.executable, "scripts/pmos.py", *args], cwd=ROOT, capture_output=True, text=True)
    if check and proc.returncode != 0:
        sys.stdout.write(proc.stdout)
        sys.stderr.write(proc.stderr)
        sys.exit(proc.returncode)
    return proc


def state_dir() -> Path:
    return Path(os.environ.get("PMOS_STATE_DIR") or ROOT / "state")


def outputs_dir() -> Path:
    return Path(os.environ.get("PMOS_OUTPUTS_DIR") or ROOT / "outputs")


def task_state(task_id: str) -> dict:
    p = state_dir() / "tasks" / f"{task_id}.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    for args in (("task", "state", task_id, "--json"), ("task", "show", task_id, "--json")):
        proc = pmos(*args)
        if proc.returncode == 0:
            try:
                return json.loads(proc.stdout)
            except json.JSONDecodeError:
                continue
    sys.exit(f"no state for task {task_id}")


def ref_for(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT.resolve()))
    except ValueError:
        return str(path.resolve())


def has_flag(argv: list[str], flag: str) -> bool:
    """True if `pmos <argv> --help` lists FLAG (probe for an interface without depending on it)."""
    proc = pmos(*argv, "--help")
    return flag in proc.stdout

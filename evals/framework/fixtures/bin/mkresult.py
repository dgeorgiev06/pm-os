#!/usr/bin/env python3
"""Write (and optionally submit) a result.json for a task, adapting to the result contract in this tree.

  mkresult.py --task ID [--status S] [--summary TEXT] [--action JSON ...] [--usage JSON]
              [--artifact REF ...] [--no-artifacts] [--outputs-json JSON] [--no-outputs]
              [--extra-json JSON] [--open-question TEXT ...] [--file PATH] [--submit]

By default the result carries one placeholder artifact under outputs/<id>/ and, when
contracts/result.schema.json has an `outputs` property, an `outputs` map with a placeholder value
for every name in the mode's `returns` (so the same case works before and after that contract change).
Placeholder documents have the sections pm:standards/prd requires, so done.must code lines pass on them.
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import ROOT, outputs_dir, ref_for, task_state  # noqa: E402


# Shaped like a document so a mode's done.must code lines (e.g. pm/prd's `standard` line, check_doc.py) pass on it.
PLACEHOLDER = """# {name}

Placeholder written by the framework evals.

## Problem
A fixture.

## Personas
- Fixture reader

## Requirements
- R1: The fixture exists.

## Success metrics
- The case passes.

## Open questions
- None (owner: framework evals).
"""


def placeholder(task_id: str, name: str) -> str:
    p = outputs_dir() / task_id / f"{name}.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    if not p.exists():
        p.write_text(PLACEHOLDER.format(name=name), encoding="utf-8")
    return ref_for(p)


def default_outputs(task: dict, task_id: str) -> dict:
    mode_dir = ROOT / task["mode_dir"]
    man = yaml.safe_load((mode_dir / "mode.yaml").read_text(encoding="utf-8")) or {}
    out = {}
    for name, typ in (man.get("returns") or {}).items():
        base = str(typ).rstrip("?")
        out[name] = {"list": [], "object": {}, "number": 0, "integer": 0, "bool": True,
                     "boolean": True, "string": "x"}.get(base) if base not in ("doc_ref", "diff_ref") \
            else placeholder(task_id, name)
    return out


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--task", required=True)
    p.add_argument("--status", default="done", choices=["done", "needs_approval", "blocked", "failed"])
    p.add_argument("--summary", default="Fixture result written by the framework evals.")
    p.add_argument("--action", action="append", default=[])
    p.add_argument("--usage")
    p.add_argument("--artifact", action="append")
    p.add_argument("--no-artifacts", action="store_true")
    p.add_argument("--outputs-json")
    p.add_argument("--no-outputs", action="store_true")
    p.add_argument("--extra-json")
    p.add_argument("--open-question", action="append")
    p.add_argument("--file")
    p.add_argument("--submit", action="store_true")
    a = p.parse_args()

    task = task_state(a.task)
    result = {"task_id": a.task, "status": a.status, "summary": a.summary}
    if not a.no_artifacts:
        refs = a.artifact or [placeholder(a.task, "artifact")]
        result["artifacts"] = [{"kind": "doc", "ref": r} for r in refs]
    if a.action:
        result["actions"] = [json.loads(x) for x in a.action]
    if a.usage:
        result["usage"] = json.loads(a.usage)
    if a.status == "blocked":
        result["open_questions"] = a.open_question or ["Fixture question?"]
    elif a.open_question:
        result["open_questions"] = a.open_question
    result["self_check"] = [{"criterion": "fixture", "met": True}]
    schema = json.loads((ROOT / "contracts" / "result.schema.json").read_text(encoding="utf-8"))
    if a.outputs_json is not None:
        result["outputs"] = json.loads(a.outputs_json)
    elif not a.no_outputs and "outputs" in schema.get("properties", {}) and a.status in ("done", "needs_approval"):
        result["outputs"] = default_outputs(task, a.task)
    if a.extra_json:
        result.update(json.loads(a.extra_json))

    path = Path(a.file) if a.file else outputs_dir() / a.task / "result.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    if not a.submit:
        print(ref_for(path))
        return 0
    proc = subprocess.run([sys.executable, "scripts/pmos.py", "task", "result", a.task, ref_for(path)],
                          cwd=ROOT, capture_output=True, text=True)
    sys.stdout.write(proc.stdout)
    sys.stderr.write(proc.stderr)
    return proc.returncode


if __name__ == "__main__":
    sys.exit(main())

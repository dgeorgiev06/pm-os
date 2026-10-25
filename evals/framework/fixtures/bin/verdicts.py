#!/usr/bin/env python3
"""Print a review verdicts file for a task, built from `pmos task show ID --checklist`.

  verdicts.py --task ID [--fail LINE_ID ...] [--drop N] [--score N]

--fail marks those checklist lines as failing; --drop leaves out the last N lines (to test that
pmos refuses incomplete verdicts). Each verdict carries `evidence`, and a failed one a `fix`;
settled lines (code lines pmos ran) get none. --score is written only for a tree whose review
still takes one (a checklist without `kind`).
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import pmos  # noqa: E402


def checklist(task_id: str) -> list[dict]:
    proc = pmos("task", "show", task_id, "--checklist", check=True)
    return json.loads(proc.stdout)


def build(task_id: str, fail=(), drop: int = 0, score: float = 5) -> dict:
    items = checklist(task_id)
    lines = []
    for c in items:
        if c.get("settled"):
            continue
        line = {"id": c["id"], "pass": c["id"] not in set(fail), "note": "framework-eval verdict",
                "evidence": "framework-eval: the fixture artifact"}
        if not line["pass"]:
            line["fix"] = "framework-eval fix"
        lines.append(line)
    if drop:
        lines = lines[:-drop]
    if items and "kind" in items[0]:      # the score comes from the should lines
        return {"lines": lines}
    return {"score": score, "lines": lines}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--task", required=True)
    p.add_argument("--fail", action="append", default=[])
    p.add_argument("--drop", type=int, default=0)
    p.add_argument("--score", type=float, default=5)
    a = p.parse_args()
    print(json.dumps(build(a.task, a.fail, a.drop, a.score), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

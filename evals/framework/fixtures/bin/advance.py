#!/usr/bin/env python3
"""Drive a task through review and approval until it reaches a target state.

  advance.py --task ID --to STATE [--by pm]

in_review -> passing review (per-line verdicts when `task review` supports --verdicts, otherwise
--passed true --score 5); awaiting_approval -> `task approve --by pm`; approved -> `task move done`.
It never edits state files. Used only to set up a case, never as the step under test.
"""
import argparse
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import has_flag, pmos, task_state  # noqa: E402
import verdicts  # noqa: E402


def review_pass(task_id: str) -> None:
    if has_flag(["task", "review"], "--verdicts"):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(verdicts.build(task_id), f)
        pmos("task", "review", task_id, "--verdicts", f.name, "--note", "framework-eval pass", check=True)
    else:
        pmos("task", "review", task_id, "--passed", "true", "--score", "5", "--note", "framework-eval pass",
             check=True)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--task", required=True)
    p.add_argument("--to", required=True)
    p.add_argument("--by", default="pm")
    a = p.parse_args()
    for _ in range(6):
        state = task_state(a.task)["state"]
        if state == a.to:
            print(f"{a.task}: {state}")
            return 0
        if state == "in_review":
            review_pass(a.task)
        elif state == "awaiting_approval":
            pmos("task", "approve", a.task, "--by", a.by, check=True)
        elif state == "approved":
            pmos("task", "move", a.task, "done", "--by", "operator", "--note", "framework-eval", check=True)
        else:
            print(f"{a.task}: can't advance from {state} to {a.to}", file=sys.stderr)
            return 1
    print(f"{a.task}: did not reach {a.to}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())

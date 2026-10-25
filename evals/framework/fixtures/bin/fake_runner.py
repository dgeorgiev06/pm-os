#!/usr/bin/env python3
"""A stand-in for eval.command: runs the `task new` command from a rendered prompt.md, writes a
file into the task's outputs folder, and records the task id. Prints what it saw.

  fake_runner.py PROMPT_FILE
"""
import os
import re
import subprocess
import sys
from pathlib import Path

prompt = Path(sys.argv[1]).read_text(encoding="utf-8")
m = re.search(r"```\n(python[^\n]*task new[^\n]*)\n```", prompt)
if not m:
    print("fake-runner: no task new command in the prompt")
    sys.exit(1)
cmd = re.sub(r"^python3? ", f'"{sys.executable}" ', m.group(1))
proc = subprocess.run(cmd, shell=True, capture_output=True, text=True)
ids = re.findall(r"T-\d{8}-\d+", proc.stdout)
if proc.returncode != 0 or not ids:
    print(f"fake-runner: task new failed: {proc.stdout} {proc.stderr}")
    sys.exit(1)
task_id = ids[-1]
out_env = os.environ.get("PMOS_OUTPUTS_DIR")
out_dir = Path(out_env) if out_env else Path("outputs")
(out_dir / task_id).mkdir(parents=True, exist_ok=True)
(out_dir / task_id / "ran.txt").write_text("fake runner\n", encoding="utf-8")
Path("build").mkdir(exist_ok=True)
with open("build/fake-runner-ids.txt", "a", encoding="utf-8") as f:
    f.write(task_id + "\n")
print(f"task_id={task_id}")
print(f"outputs_dir={out_env or 'NONE'}")
print(f"state_dir={os.environ.get('PMOS_STATE_DIR') or 'NONE'}")

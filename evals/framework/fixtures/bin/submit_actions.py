#!/usr/bin/env python3
"""Submit a task's result with every action in an actions file (JSON list) as needs_approval.

  submit_actions.py TASK OUTPUTS_JSON ACTIONS_FILE

Calls mkresult.py --submit once, passing each action with --action. Used only to set up a case.
"""
import json
import os
import subprocess
import sys

task, outputs, actions_file = sys.argv[1:4]
here = os.path.dirname(os.path.abspath(__file__))
cmd = [sys.executable, os.path.join(here, "mkresult.py"), "--task", task, "--status", "needs_approval",
       "--submit", "--outputs-json", outputs]
for action in json.load(open(actions_file, encoding="utf-8")):
    cmd += ["--action", json.dumps(action)]
sys.exit(subprocess.run(cmd).returncode)

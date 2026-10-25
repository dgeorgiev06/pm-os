"""Fixture script: `tool.py` prints "tool ok"; `tool.py --fail` exits 1; `tool.py ACTION.json` applies an action."""
import json
import sys

args = sys.argv[1:]
if args and args[0] == "--fail":
    print("tool failed on purpose")
    sys.exit(1)
if args and args[-1].endswith(".json"):
    spec = json.load(open(args[-1], encoding="utf-8"))
    print("applied", spec["action"]["idempotency_key"])
    sys.exit(0)
print("tool ok")

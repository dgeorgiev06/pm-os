#!/usr/bin/env python3
"""Set one value in a YAML or JSON file (comments are not kept). For setting up cases only.

  yset.py FILE PATH VALUE [--str]

PATH is dotted: `grants.jira`, `packs.[name=gtm].grants_approved.jira`, `result.actions.0.payload`.
VALUE is parsed as YAML (so `[a, b]`, `0.3.0`, `true` work) unless --str is given.
"""
import json
import sys
from pathlib import Path

import yaml


def main() -> int:
    args = [a for a in sys.argv[1:] if a != "--str"]
    as_str = "--str" in sys.argv
    if len(args) != 3:
        print(__doc__)
        return 2
    path, dotted, raw = Path(args[0]), args[1], args[2]
    is_json = path.suffix == ".json"
    data = json.loads(path.read_text(encoding="utf-8")) if is_json else yaml.safe_load(path.read_text(encoding="utf-8"))
    value = raw if as_str else yaml.safe_load(raw)
    parts = dotted.split(".")
    cur = data
    for i, part in enumerate(parts):
        last = i == len(parts) - 1
        if part.startswith("[") and part.endswith("]"):
            k, _, v = part[1:-1].partition("=")
            idx = next(j for j, item in enumerate(cur) if str(item.get(k)) == v)
            key = idx
        elif isinstance(cur, list):
            key = int(part)
        else:
            key = part
        if last:
            cur[key] = value
        else:
            if isinstance(cur, dict) and key not in cur:
                cur[key] = {}
            cur = cur[key]
    text = json.dumps(data, indent=2) + "\n" if is_json else yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
    path.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())

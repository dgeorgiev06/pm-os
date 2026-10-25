#!/usr/bin/env python3
"""send — the send handler of a channel in this pack (pack.yaml `actions:`, channel.yaml `send.handler`).

Usage: send.py CHANNEL ACTION.json   (the actions: line passes the channel name)
       send.py ACTION.json           (the channel is the one the action's payload names)

It checks the action against the channel (its ref, limits, recipient pattern, via `pmos channel check`), then:
  - no receipt in the action file: prints {"sent": false, "verified": true} and exits 0 (not sent yet);
  - a "receipt" in the action file (pmos action run --receipt): prints {"sent": true, "receipt": ...}.
A channel with no tool mapped in pm-os.yaml (adapters.claude-code.channel_tools) is refused: not configured.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import yaml

PACK_DIR = Path(__file__).resolve().parent.parent


def pm_os_root() -> Path:
    if os.environ.get("PMOS_ROOT"):
        return Path(os.environ["PMOS_ROOT"]).resolve()
    for d in Path(__file__).resolve().parents:
        if (d / "pm-os.yaml").exists():
            return d
    sys.exit("error: can't find the pm-os repo; set PMOS_ROOT")


def fail(msg: str) -> int:
    print(f"error: {msg}", file=sys.stderr)
    return 1


def main() -> int:
    args = sys.argv[1:]
    if len(args) == 1:
        channel, action_path = None, args[0]
    elif len(args) == 2:
        channel, action_path = args
    else:
        print("usage: send.py [CHANNEL] ACTION.json", file=sys.stderr)
        return 2
    root = pm_os_root()
    try:
        act = json.loads(Path(action_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        return fail(f"{action_path}: not an action file ({e})")
    action = act.get("action") or {}
    if action.get("system") != "comms" or action.get("op") != "send":
        return fail(f"{action_path}: not a comms.send action")
    payload = action.get("payload") or {}
    pack = yaml.safe_load((PACK_DIR / "pack.yaml").read_text(encoding="utf-8"))["name"]
    name = channel or str(payload.get("channel", "")).split("/")[-1]
    ref = f"{pack}:channel/{name}"
    spec_path = PACK_DIR / "channels" / name / "channel.yaml"
    if not spec_path.exists():
        return fail(f"unknown channel '{payload.get('channel')}' for this handler (this pack sends {ref})")
    if payload.get("channel") != ref:
        return fail(f"this handler sends {ref}, not '{payload.get('channel')}'")
    spec = yaml.safe_load(spec_path.read_text(encoding="utf-8"))

    check = subprocess.run([sys.executable, str(root / "scripts" / "pmos.py"), "channel", "check", ref,
                            "--text", "-", "--recipient", str(payload.get("recipient", ""))],
                           cwd=root, input=str(payload.get("text", "")), capture_output=True, text=True)
    if check.returncode != 0:
        sys.stderr.write(check.stderr)
        return 1

    mapping = (((yaml.safe_load((root / "pm-os.yaml").read_text(encoding="utf-8")) or {}).get("adapters") or {})
               .get("claude-code") or {}).get("channel_tools") or {}
    tools = mapping.get(ref) or mapping.get(spec["system"]) or []
    if not tools:
        return fail(f"{ref} is not configured: map it under adapters.claude-code.channel_tools in pm-os.yaml "
                    f"(e.g. {ref}: [your MCP send tool])")

    receipt = act.get("receipt")
    if receipt:
        print(json.dumps({"sent": True, "receipt": str(receipt), "channel": ref}))
    else:
        print(json.dumps({"sent": False, "verified": True, "channel": ref, "tools": tools,
                          "note": "send with one of these tools, then record its id with --receipt"}))
    return 0


if __name__ == "__main__":
    sys.exit(main())

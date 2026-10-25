#!/usr/bin/env python3
"""build_actions — notifications for cos/notify: check a draft, render its messages, propose the sends.

  --check FILE                 a draft (notifications) or a messages file (messages). Every problem is
                               printed, each naming its entry or field; exit 1 on any.
  build DRAFT --audience A --task ID --out DIR [--channels a,b] [--send-at S]
                               check the draft and render it for one audience. Writes DIR/messages.json
                               and DIR/actions.json: one comms.send action per channel and recipient.
  merge OUT IN [IN ...]        join messages files (a parent task's, from its notify children).
  send ACTION.json             the comms.send handler `pmos action run` calls. It re-verifies one action
                               and refuses until pm-os.yaml maps comms:send to a tool.

Channels: PMOS_CHANNELS_FILE, else context/channels.yaml (copy context/channels.example.yaml).
Recipients come only from that file. Templates are in modes/notify/templates/ (generic) or next to the
mode that uses them; each has YAML front matter with its audience, channel, max_words and fields.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path

import yaml

SCRIPT_DIR = Path(__file__).resolve().parent
TEMPLATES = SCRIPT_DIR.parent / "templates"
TYPES = {"string", "number", "integer", "bool", "list", "date"}
CHANNEL_KINDS = {"slack", "email"}
AUDIENCES = {"internal", "external"}
FRONT = re.compile(r"\A---\n(.*?)\n---\n(.*)\Z", re.S)
BLOCK = re.compile(r"\{\{#(\w+)\}\}(.*?)\{\{/\1\}\}", re.S)
PLACEHOLDER = re.compile(r"\{\{[^{}]*\}\}")


def find_root() -> Path:
    """The pm-os repo: PMOS_ROOT, else the nearest folder above this script that holds pm-os.yaml."""
    if os.environ.get("PMOS_ROOT"):
        return Path(os.environ["PMOS_ROOT"]).resolve()
    for d in SCRIPT_DIR.parents:
        if (d / "pm-os.yaml").exists() and (d / "scripts" / "pmos.py").exists():
            return d
    raise SystemExit("error: can't find the pm-os repo (no pm-os.yaml above this script); set PMOS_ROOT")


ROOT = find_root()


def rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


def words(text: str) -> int:
    """Whitespace tokens with a letter or digit, as lint counts them."""
    return sum(1 for t in text.split() if re.search(r"[A-Za-z0-9]", t))


# --------------------------------------------------------------------------- channels
class Channels:
    def __init__(self, data: dict, where: str):
        self.where = where
        self.internal_only = set(data.get("internal_only_fields") or [])
        self.audiences: dict[str, list[dict]] = {}
        for aud, spec in (data.get("audiences") or {}).items():
            chans = []
            for c in (spec or {}).get("channels") or []:
                target = c.get("target")
                targets = target if isinstance(target, list) else [target]
                chans.append({"name": c["name"], "kind": c["kind"], "targets": [str(t) for t in targets if t]})
            self.audiences[aud] = chans

    def find(self, name: str) -> tuple[str, dict] | None:
        for aud, chans in self.audiences.items():
            for c in chans:
                if c["name"] == name:
                    return aud, c
        return None


def load_channels() -> Channels:
    path = Path(os.environ["PMOS_CHANNELS_FILE"]) if os.environ.get("PMOS_CHANNELS_FILE") \
        else ROOT / "context" / "channels.yaml"
    if not path.exists():
        raise Problem(f"no channels file at {path}; copy context/channels.example.yaml to context/channels.yaml")
    return Channels(yaml.safe_load(path.read_text(encoding="utf-8")) or {}, rel(path))


class Problem(Exception):
    pass


# --------------------------------------------------------------------------- templates
def generic_template(channel: str) -> Path:
    return TEMPLATES / f"generic-{channel}.md"


def load_template(ref: str, cfg: Channels) -> dict:
    path = Path(ref) if Path(ref).is_absolute() else ROOT / ref
    if not path.exists():
        raise Problem(f"template '{ref}' not found")
    m = FRONT.match(path.read_text(encoding="utf-8"))
    if not m:
        raise Problem(f"template '{ref}' has no YAML front matter")
    meta = yaml.safe_load(m.group(1)) or {}
    fields = meta.get("fields") or {}
    for name, spec in fields.items():
        if spec.get("type") not in TYPES:
            raise Problem(f"template '{ref}': field '{name}' has type '{spec.get('type')}'; use one of {sorted(TYPES)}")
    if meta.get("audience") == "external":
        leaked = sorted(set(fields) & cfg.internal_only)
        if leaked:
            raise Problem(f"template '{ref}' is external but declares internal-only field '{leaked[0]}'")
    return {"ref": ref, "audience": meta.get("audience", "any"), "channel": meta.get("channel"),
            "max_words": int(meta.get("max_words", 250)), "fields": fields, "body": m.group(2).rstrip("\n")}


# --------------------------------------------------------------------------- draft checks
def check_field(name: str, spec: dict, value, label: str) -> list[str]:
    problems = []
    kind = spec.get("type")
    if kind == "string" or kind == "date":
        ok = isinstance(value, str)
    elif kind == "number":
        ok = isinstance(value, (int, float)) and not isinstance(value, bool)
    elif kind == "integer":
        ok = isinstance(value, int) and not isinstance(value, bool)
    elif kind == "bool":
        ok = isinstance(value, bool)
    else:
        ok = isinstance(value, list)
    if not ok:
        return [f"{label}: field '{name}' should be {kind}, is {type(value).__name__}"]
    if kind == "date":
        try:
            dt.date.fromisoformat(value)
        except ValueError:
            problems.append(f"{label}: field '{name}' is not a date (use YYYY-MM-DD)")
    if kind == "list" and len(value) < int(spec.get("min", 0)):
        problems.append(f"{label}: field '{name}' needs at least {spec['min']} item(s)")
    if spec.get("max_words") and words(str(value)) > int(spec["max_words"]):
        problems.append(f"{label}: field '{name}' is {words(str(value))} words, over max_words "
                        f"({spec['max_words']})")
    return problems


def render(body: str, fields: dict) -> str:
    def block(m):
        return m.group(2) if fields.get(m.group(1)) not in (None, "", []) else ""

    def sub(m):
        value = fields.get(m.group(1))
        if value is None:
            return m.group(0)
        if isinstance(value, list):
            return "\n".join(f"- {x}" for x in value)
        if isinstance(value, bool):
            return "yes" if value else "no"
        return str(value)

    text = BLOCK.sub(block, body)
    text = re.sub(r"\{\{(\w+)\}\}", sub, text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def check_draft(draft: dict, cfg: Channels) -> tuple[list[dict], list[str]]:
    """Returns the rendered entries and every problem found."""
    problems: list[str] = []
    if not isinstance(draft, dict) or not isinstance(draft.get("notifications"), list) or not draft["notifications"]:
        return [], ["draft: 'notifications' must be a non-empty list"]
    for k in draft:
        if k != "notifications":
            problems.append(f"draft: unknown top-level key '{k}'")
    rendered = []
    for i, entry in enumerate(draft["notifications"], 1):
        label = f"entry {i}"
        if not isinstance(entry, dict):
            problems.append(f"{label}: must be an object")
            continue
        for k in entry:
            if k == "recipient" or k == "to":
                problems.append(f"{label}: unknown key '{k}'; recipients come from channels.yaml, never from the draft")
            elif k not in ("template", "channel", "audience", "fields"):
                problems.append(f"{label}: unknown key '{k}'")
        try:
            if entry.get("template"):
                tpl = load_template(entry["template"], cfg)
            else:
                channel, aud = entry.get("channel"), entry.get("audience")
                if channel not in CHANNEL_KINDS or aud not in AUDIENCES:
                    problems.append(f"{label}: without a template it needs channel (slack|email) and audience "
                                    f"(internal|external)")
                    continue
                tpl = load_template(rel(generic_template(channel)), cfg)
        except Problem as e:
            problems.append(f"{label}: {e}")
            continue
        audience = tpl["audience"]
        if audience == "any":
            audience = entry.get("audience")
        elif entry.get("audience") not in (None, audience):
            problems.append(f"{label}: audience '{entry.get('audience')}' does not match its template ({audience})")
        if audience not in AUDIENCES:
            problems.append(f"{label}: audience must be internal or external, is '{audience}'")
            continue
        fields = entry.get("fields") or {}
        if not isinstance(fields, dict):
            problems.append(f"{label}: 'fields' must be an object")
            continue
        for name in fields:
            if name not in tpl["fields"]:
                problems.append(f"{label}: unknown field '{name}' for {tpl['ref']}")
            elif audience == "external" and name in cfg.internal_only:
                problems.append(f"{label}: external entry sets internal-only field '{name}'")
        for name, spec in tpl["fields"].items():
            if fields.get(name) in (None, ""):
                if spec.get("required"):
                    problems.append(f"{label}: required field '{name}' is missing")
                continue
            if name in fields:
                problems += check_field(name, spec, fields[name], label)
        text = render(tpl["body"], fields)
        for leftover in sorted(set(PLACEHOLDER.findall(text))):
            problems.append(f"{label}: leftover placeholder {leftover} in the text")
        if words(text) > tpl["max_words"]:
            problems.append(f"{label}: message is {words(text)} words, over max_words ({tpl['max_words']})")
        rendered.append({"index": i, "audience": audience, "channel": entry.get("channel") or tpl["channel"],
                         "template": tpl["ref"], "fields": fields, "text": text, "max_words": tpl["max_words"]})
    # nothing from the internal-only section may reach an external message
    for ext in [r for r in rendered if r["audience"] == "external"]:
        for other in [r for r in rendered if r["audience"] != "external"]:
            for name in cfg.internal_only:
                value = other["fields"].get(name)
                for item in (value if isinstance(value, list) else [value]):
                    if isinstance(item, str) and len(item) >= 4 and item.lower() in ext["text"].lower():
                        problems.append(f"entry {ext['index']}: external text repeats internal-only text from "
                                        f"entry {other['index']} ({name})")
    return rendered, problems


def check_messages(doc: dict, cfg: Channels) -> tuple[int, list[str]]:
    problems = []
    if doc.get("contract") != "notify-messages@1":
        problems.append("messages: contract must be notify-messages@1")
    msgs = doc.get("messages") or []
    keys = [m.get("idempotency_key") for m in msgs]
    if len(set(keys)) != len(keys):
        problems.append("messages: idempotency keys must be unique")
    for i, m in enumerate(msgs, 1):
        label = f"message {i}"
        text = m.get("text", "")
        for leftover in sorted(set(PLACEHOLDER.findall(text))):
            problems.append(f"{label}: leftover placeholder {leftover} in the text")
        if m.get("max_words") and words(text) > int(m["max_words"]):
            problems.append(f"{label}: message is {words(text)} words, over max_words ({m['max_words']})")
        found = cfg.find(m.get("channel", ""))
        if not found:
            problems.append(f"{label}: unknown channel '{m.get('channel')}'")
        elif m.get("recipient") not in found[1]["targets"]:
            problems.append(f"{label}: unknown recipient '{m.get('recipient')}' for channel {m.get('channel')}")
    return len(msgs), problems


def load_json(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        raise Problem(f"{path}: not found")
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise Problem(f"{path}: not JSON ({e})")


def fail(problems: list[str]) -> int:
    for p in problems:
        print(f"error: {p}", file=sys.stderr)
    return 1


# --------------------------------------------------------------------------- commands
def cmd_check(path: str) -> int:
    cfg = load_channels()
    doc = load_json(path)
    if "messages" in doc:
        n, problems = check_messages(doc, cfg)
        if problems:
            return fail([f"{path}: {p}" for p in problems])
        print(f"ok: {path}: {n} message(s) checked")
        return 0
    rendered, problems = check_draft(doc, cfg)
    if problems:
        return fail([f"{path}: {p}" for p in problems])
    print(f"ok: {path}: {len(rendered)} notification(s) checked")
    return 0


def cmd_build(a) -> int:
    if a.audience not in AUDIENCES:
        return fail([f"audience '{a.audience}' is not internal or external"])
    cfg = load_channels()
    doc = load_json(a.draft)
    rendered, problems = check_draft(doc, cfg)
    wanted = [c for c in (a.channels or "").split(",") if c]
    known = {c["name"] for c in cfg.audiences.get(a.audience, [])}
    problems += [f"unknown channel '{c}' for {a.audience}" for c in wanted if c not in known]
    if problems:
        return fail([f"{a.draft}: {p}" for p in problems])
    messages, actions, n = [], [], 0
    for r in [r for r in rendered if r["audience"] == a.audience]:
        chans = [c for c in cfg.audiences.get(a.audience, []) if c["kind"] == r["channel"]
                 and (not wanted or c["name"] in wanted)]
        if not chans:
            problems.append(f"entry {r['index']}: no {r['channel']} channel for {a.audience} in channels.yaml")
            continue
        for c in chans:
            for target in c["targets"]:
                n += 1
                key = f"{a.task}-{c['name']}-{n}"
                messages.append({"audience": a.audience, "channel": c["name"], "kind": c["kind"],
                                 "template": r["template"], "recipient": target, "text": r["text"],
                                 "words": words(r["text"]), "max_words": r["max_words"],
                                 "idempotency_key": key, "send_at": a.send_at})
                actions.append({"system": "comms", "op": "send", "idempotency_key": key,
                                "payload": {"audience": a.audience, "channel": c["name"], "kind": c["kind"],
                                            "recipient": target, "text": r["text"], "send_at": a.send_at},
                                "preview": r["text"]})
    if not messages and not problems:
        problems.append(f"no notification for audience {a.audience}")
    if problems:
        return fail([f"{a.draft}: {p}" for p in problems])
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "messages.json").write_text(json.dumps({"contract": "notify-messages@1", "task": a.task,
                                                   "audience": a.audience, "messages": messages},
                                                  indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (out / "actions.json").write_text(json.dumps(actions, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"build: {len(actions)} comms.send action(s) for {a.audience}; wrote {a.out}/messages.json "
          f"and {a.out}/actions.json")
    return 0


def cmd_merge(a) -> int:
    merged = []
    for path in a.inputs:
        merged += load_json(path).get("messages", [])
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps({"contract": "notify-messages@1", "messages": merged},
                                      indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"merge: {len(merged)} message(s) into {a.out}")
    return 0


def cmd_send(path: str) -> int:
    act = load_json(path)
    if not isinstance(act, dict) or not isinstance(act.get("action"), dict):
        return fail([f"{path}: not an action file (expected {{\"task_id\", \"action\"}}, as pmos action run writes it)"])
    action = act["action"]
    if action.get("system") != "comms" or action.get("op") != "send":
        return fail([f"{path}: not a comms.send action"])
    payload = action.get("payload") or {}
    cfg = load_channels()
    found = cfg.find(payload.get("channel", ""))
    if not found:
        return fail([f"{path}: unknown channel '{payload.get('channel')}'"])
    if payload.get("recipient") not in found[1]["targets"]:
        return fail([f"{path}: unknown recipient '{payload.get('recipient')}' for channel {payload.get('channel')}"])
    if PLACEHOLDER.search(payload.get("text", "")):
        return fail([f"{path}: leftover placeholder in the text"])
    pm_os = yaml.safe_load((ROOT / "pm-os.yaml").read_text(encoding="utf-8")) or {}
    tools = (((pm_os.get("adapters") or {}).get("claude-code") or {}).get("grants_to_tools") or {}).get("comms:send") or []
    if not tools:
        return fail(["comms.send is not configured: set adapters.claude-code.grants_to_tools comms:send in "
                     "pm-os.yaml to your Slack/email MCP tool names"])
    print(f"recorded: comms.send {action.get('idempotency_key')} to {payload['recipient']} via "
          f"{', '.join(tools)} (verified; the Operator sends it with that tool)")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--check", metavar="FILE", help="check a draft or a messages file")
    sub = p.add_subparsers(dest="cmd")
    b = sub.add_parser("build", help="check a draft and write its messages and actions")
    b.add_argument("draft")
    b.add_argument("--audience", required=True)
    b.add_argument("--task", required=True)
    b.add_argument("--out", required=True)
    b.add_argument("--channels", default="", help="comma-separated channel names from channels.yaml")
    b.add_argument("--send-at", dest="send_at", default=None)
    m = sub.add_parser("merge", help="join messages files")
    m.add_argument("out")
    m.add_argument("inputs", nargs="+")
    s = sub.add_parser("send", help="the comms.send handler (pmos action run)")
    s.add_argument("action")
    a = p.parse_args()
    try:
        if a.check:
            return cmd_check(a.check)
        if a.cmd == "build":
            return cmd_build(a)
        if a.cmd == "merge":
            return cmd_merge(a)
        if a.cmd == "send":
            return cmd_send(a.action)
        p.print_help(sys.stderr)
        return 2
    except Problem as e:
        return fail([str(e)])


if __name__ == "__main__":
    sys.exit(main())

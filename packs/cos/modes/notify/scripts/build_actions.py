#!/usr/bin/env python3
"""build_actions — notifications for cos/notify: check a draft, render its messages, propose the sends.

  --check FILE                 a draft (notifications) or a messages file (messages). Every problem is
                               printed, each naming its entry or field; exit 1 on any.
  build DRAFT --audience A --task ID --out DIR [--channels a,b] [--send-at S]
                               check the draft and render it for one audience. Writes DIR/messages.json
                               and DIR/actions.json: one comms.send action per channel and recipient.
  merge OUT IN [IN ...]        join messages files (a parent task's, from its notify children).
  send ACTION.json             the comms.send handler: forwards the action to its channel's own send handler
                               (channel.yaml send.handler, in the channel's pack), which checks it and replies.

A channel is a registry ref, `<pack>:channel/<name>` (`pmos channel show`): its format, limits and recipient
come from there, and an unknown or invisible one is refused with the channels that are known. Recipients come
only from context/channels.yaml (PMOS_CHANNELS_FILE overrides). Templates are in modes/notify/templates/
(generic-<format>.md) or next to the mode that uses them. Each has YAML front matter (audience, an optional
channel ref, max_words, fields); its body is Markdown, rendered into the channel's format.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

import yaml

SCRIPT_DIR = Path(__file__).resolve().parent
TEMPLATES = SCRIPT_DIR.parent / "templates"
TYPES = {"string", "number", "integer", "bool", "list", "date"}
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


class Problem(Exception):
    pass


def pmos(*args: str, stdin: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(ROOT / "scripts" / "pmos.py"), *args], cwd=ROOT,
                          input=stdin, capture_output=True, text=True)


def pmos_problems(proc: subprocess.CompletedProcess) -> list[str]:
    lines = [ln.replace("error: ", "", 1) for ln in (proc.stderr or proc.stdout).splitlines() if ln.strip()]
    return lines or ["the channel check failed"]


def words(text: str) -> int:
    """Whitespace tokens with a letter or digit, as lint counts them."""
    return sum(1 for t in text.split() if re.search(r"[A-Za-z0-9]", t))


# --------------------------------------------------------------------------- channels (the registry)
_CHANNELS: dict[str, dict] = {}


def channel_info(ref: str) -> dict:
    """pmos channel show REF --from cos: format, limits, recipient, send command. Cached per run."""
    if ref not in _CHANNELS:
        proc = pmos("channel", "show", str(ref), "--from", "cos", "--json")
        if proc.returncode != 0:
            raise Problem(pmos_problems(proc)[-1])
        _CHANNELS[ref] = json.loads(proc.stdout)
    return _CHANNELS[ref]


def channel_problems(ref: str, text: str, recipient: str | None = None) -> list[str]:
    """The channel's limits and recipient pattern, checked by pmos (CH4)."""
    args = ["channel", "check", ref, "--text", "-", "--from", "cos"]
    if recipient is not None:
        args += ["--recipient", str(recipient)]
    proc = pmos(*args, stdin=text)
    return [] if proc.returncode == 0 else pmos_problems(proc)


def channel_render(ref: str, text: str) -> str:
    proc = pmos("channel", "render", ref, "--text", "-", "--from", "cos", stdin=text)
    if proc.returncode != 0:
        raise Problem(pmos_problems(proc)[-1])
    return proc.stdout[:-1] if proc.stdout.endswith("\n") else proc.stdout


# --------------------------------------------------------------------------- channels.yaml (recipients)
class Channels:
    """context/channels.yaml: per audience, the channels (registry refs) and their recipients."""

    def __init__(self, data: dict):
        self.internal_only = set(data.get("internal_only_fields") or [])
        self.audiences: dict[str, list[dict]] = {}
        for aud, spec in (data.get("audiences") or {}).items():
            chans = []
            for c in (spec or {}).get("channels") or []:
                target = c.get("target")
                targets = target if isinstance(target, list) else [target]
                chans.append({"name": c["name"], "channel": c["channel"], "targets": [str(t) for t in targets if t]})
            self.audiences[aud] = chans

    def find(self, ref: str) -> tuple[str, dict] | None:
        for aud, chans in self.audiences.items():
            for c in chans:
                if c["channel"] == ref:
                    return aud, c
        return None


def load_channels() -> Channels:
    path = Path(os.environ["PMOS_CHANNELS_FILE"]) if os.environ.get("PMOS_CHANNELS_FILE") \
        else ROOT / "context" / "channels.yaml"
    if not path.exists():
        raise Problem(f"no channels file at {path}; copy context/channels.example.yaml to context/channels.yaml")
    return Channels(yaml.safe_load(path.read_text(encoding="utf-8")) or {})


# --------------------------------------------------------------------------- templates
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
            "format": meta.get("format"),
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
    """Returns the rendered entries (text in each channel's format) and every problem found."""
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
                if not channel or aud not in AUDIENCES:
                    problems.append(f"{label}: without a template it needs channel (a registry ref, e.g. "
                                    f"channels:channel/slack) and audience (internal|external)")
                    continue
                generic = TEMPLATES / f"generic-{channel_info(channel)['format']}.md"
                if not generic.exists():
                    raise Problem(f"no generic template for {channel} ({generic.name}); name a template")
                tpl = load_template(rel(generic), cfg)
        except Problem as e:
            problems.append(f"{label}: {e}")
            continue
        channel = entry.get("channel") or tpl["channel"]
        if not channel:
            problems.append(f"{label}: no channel (the template names none and the entry gives none)")
            continue
        if tpl["channel"] and entry.get("channel") and entry["channel"] != tpl["channel"]:
            problems.append(f"{label}: channel '{entry['channel']}' does not match its template ({tpl['channel']})")
            continue
        try:
            info = channel_info(channel)
        except Problem as e:
            problems.append(f"{label}: {e}")
            continue
        if tpl["format"] and tpl["format"] != info["format"]:
            problems.append(f"{label}: template {tpl['ref']} is {tpl['format']}, but {channel} sends {info['format']}")
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
        try:
            text = channel_render(channel, text)
        except Problem as e:
            problems.append(f"{label}: {e}")
            continue
        if words(text) > tpl["max_words"]:
            problems.append(f"{label}: message is {words(text)} words, over max_words ({tpl['max_words']})")
        problems += [f"{label}: {p}" for p in channel_problems(channel, text)]
        rendered.append({"index": i, "audience": audience, "channel": channel, "format": info["format"],
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
        ref = m.get("channel", "")
        try:
            channel_info(ref)
        except Problem as e:
            problems.append(f"{label}: {e}")
            continue
        found = cfg.find(ref)
        if not found:
            problems.append(f"{label}: channel '{ref}' is not in channels.yaml")
        elif m.get("recipient") not in found[1]["targets"]:
            problems.append(f"{label}: unknown recipient '{m.get('recipient')}' for channel {ref}")
        problems += [f"{label}: {p}" for p in channel_problems(ref, text, m.get("recipient"))]
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
    problems += [f"unknown channel '{c}' for {a.audience} in channels.yaml (known: {', '.join(sorted(known)) or 'none'})"
                 for c in wanted if c not in known]
    if problems:
        return fail([f"{a.draft}: {p}" for p in problems])
    messages, actions, n = [], [], 0
    for r in [r for r in rendered if r["audience"] == a.audience]:
        chans = [c for c in cfg.audiences.get(a.audience, []) if c["channel"] == r["channel"]
                 and (not wanted or c["name"] in wanted)]
        if not chans:
            problems.append(f"entry {r['index']}: no {r['channel']} channel for {a.audience} in channels.yaml")
            continue
        for c in chans:
            for target in c["targets"]:
                problems += [f"entry {r['index']}: {p}" for p in channel_problems(r["channel"], r["text"], target)]
                n += 1
                key = f"{a.task}-{c['name']}-{n}"
                messages.append({"audience": a.audience, "channel": r["channel"], "channel_name": c["name"],
                                 "format": r["format"], "template": r["template"], "recipient": target,
                                 "text": r["text"], "words": words(r["text"]), "max_words": r["max_words"],
                                 "idempotency_key": key, "send_at": a.send_at})
                actions.append({"system": "comms", "op": "send", "idempotency_key": key,
                                "payload": {"audience": a.audience, "channel": r["channel"], "recipient": target,
                                            "text": r["text"], "send_at": a.send_at},
                                "preview": f"to {target}: {r['text']}"})
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
    """comms.send: check the action against channels.yaml, then hand it to the channel's own send handler."""
    act = load_json(path)
    if not isinstance(act, dict) or not isinstance(act.get("action"), dict):
        return fail([f"{path}: not an action file (expected {{\"task_id\", \"action\"}}, as pmos action run writes it)"])
    action = act["action"]
    if action.get("system") != "comms" or action.get("op") != "send":
        return fail([f"{path}: not a comms.send action"])
    payload = action.get("payload") or {}
    cfg = load_channels()
    ref = payload.get("channel", "")
    found = cfg.find(ref)
    if not found:
        return fail([f"{path}: channel '{ref}' is not in channels.yaml"])
    if payload.get("recipient") not in found[1]["targets"]:
        return fail([f"{path}: unknown recipient '{payload.get('recipient')}' for channel {ref}"])
    if PLACEHOLDER.search(payload.get("text", "")):
        return fail([f"{path}: leftover placeholder in the text"])
    try:
        info = channel_info(ref)
    except Problem as e:
        return fail([f"{path}: {e}"])
    command = shlex.split(info["send"]["command"])
    if not command:
        return fail([f"{path}: channel {ref} has no send handler"])
    handler = ROOT / Path(info["dir"]).parent.parent / command[0]
    proc = subprocess.run([sys.executable, str(handler), *command[1:], path], cwd=ROOT,
                          capture_output=True, text=True, env={**os.environ, "PMOS_ROOT": str(ROOT)})
    sys.stdout.write(proc.stdout)
    sys.stderr.write(proc.stderr)
    return proc.returncode


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

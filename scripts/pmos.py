#!/usr/bin/env python3
"""pmos — the deterministic core of pm-os. Harness- and model-neutral.

Every state change goes through this CLI, so any agent harness (or a human) can drive the
framework the same way. Later, the same functions become steps in a durable workflow engine.

  pmos validate                         check modes, roles, skills, agents, contracts
  pmos catalog                          discover modes, write state/catalog.md (the CoS's menu)
  pmos task new --mode M --verb V --inputs JSON [...]
  pmos task show ID [--for-review] [--json]
  pmos task move ID STATE [--note TEXT] [--by WHO]
  pmos task result ID RESULT.json
  pmos task review ID --passed true|false [--score N] [--note TEXT ...]
  pmos task approve ID --by WHO [--note TEXT]
  pmos task list [--state STATE] [--all]
  pmos board                            regenerate state/status.md
  pmos decide "TEXT" [--by WHO]         append to context/decisions.log
  pmos render claude-code|generic       generate one harness's native config
  pmos eval [MODE ...]                  render (and optionally run) golden tasks

Requires: Python 3.10+, PyYAML, jsonschema (pip install -r requirements.txt).
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

try:
    import yaml
    import jsonschema
except ImportError:  # pragma: no cover
    sys.exit("pmos needs PyYAML and jsonschema: pip install -r requirements.txt")

ROOT = Path(__file__).resolve().parent.parent
TERMINAL = {"done", "failed"}
OPEN_STATES = ["queued", "running", "waiting", "in_review", "revise",
               "awaiting_approval", "approved", "blocked"]

# The task state machine. pmos is the only writer of task state.
TRANSITIONS: dict[str, set[str]] = {
    "queued": {"running", "blocked", "failed"},
    "running": {"in_review", "waiting", "blocked", "failed"},
    "waiting": {"queued", "failed"},            # queued automatically when all children finish
    "in_review": {"revise", "awaiting_approval", "done", "failed"},
    "revise": {"running", "failed"},
    "awaiting_approval": {"approved", "revise", "blocked"},
    "approved": {"done", "failed"},
    "blocked": {"queued", "failed"},
    "done": set(),
    "failed": set(),
}


class PmosError(Exception):
    pass


# --------------------------------------------------------------------------- utils
def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def load_yaml(path: Path):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_json(path: Path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path)


def frontmatter(path: Path) -> tuple[dict, str]:
    text = path.read_text(encoding="utf-8")
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", text, flags=re.S)
    if not m:
        return {}, text
    return (yaml.safe_load(m.group(1)) or {}), m.group(2)


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


# --------------------------------------------------------------------------- config
_CONFIG: dict | None = None


def config() -> dict:
    global _CONFIG
    if _CONFIG is None:
        _CONFIG = load_yaml(ROOT / "pm-os.yaml")
    return _CONFIG


def path_of(key: str) -> Path:
    overrides = {"state": "PMOS_STATE_DIR", "traces": "PMOS_TRACES_DIR"}
    env = overrides.get(key)
    if env and os.environ.get(env):
        return Path(os.environ[env]).resolve()
    return ROOT / config()["paths"][key]


def schema(name: str) -> dict:
    return load_json(ROOT / "contracts" / f"{name}.schema.json")


def validate_against(data, schema_name: str, what: str) -> None:
    validator = jsonschema.Draft202012Validator(schema(schema_name))
    errors = sorted(validator.iter_errors(data), key=lambda e: list(e.path))
    if errors:
        lines = [f"{what} does not match contracts/{schema_name}.schema.json:"]
        for e in errors[:10]:
            where = "/".join(str(p) for p in e.path) or "(root)"
            lines.append(f"  - {where}: {e.message}")
        raise PmosError("\n".join(lines))


# --------------------------------------------------------------------------- registry
def roles() -> dict:
    return load_yaml(ROOT / config()["paths"]["roles"])["roles"]


def discover_skills() -> dict[str, Path]:
    """Shared skills: id (infra/envelope-io) -> SKILL.md path."""
    base = ROOT / config()["paths"]["skills"]
    found = {}
    for skill_md in sorted(base.rglob("SKILL.md")):
        found[skill_md.parent.relative_to(base).as_posix()] = skill_md
    return found


def discover_modes() -> list[dict]:
    """All mode.yaml files under every configured mode root, with their source label."""
    cfg = config()
    sources = cfg.get("sources", {})
    modes = []
    for root_name in cfg["paths"]["modes"]:
        root = ROOT / root_name
        if not root.exists():
            continue
        for manifest in sorted(root.rglob("mode.yaml")):
            data = load_yaml(manifest) or {}
            modes.append({
                "manifest": data,
                "dir": manifest.parent,
                "path": manifest,
                "source": sources.get(root_name, "local"),
            })
    return modes


def version_tuple(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in v.split("."))


def version_matches(version: str, spec: str | None) -> bool:
    """Supports exact (1.2.0), caret (^1 / ^1.2) and tilde (~1.2). ^0.x pins the minor."""
    if not spec:
        return True
    have = version_tuple(version)
    if spec.startswith("^"):
        want = version_tuple(spec[1:])
        if want[0] == 0 and len(want) > 1:
            return have[:2] == want[:2] and have >= want + (0,) * (3 - len(want))
        return have[0] == want[0] and have >= want + (0,) * (3 - len(want))
    if spec.startswith("~"):
        want = version_tuple(spec[1:])
        return have[:2] == (want + (0,))[:2] and have >= want + (0,) * (3 - len(want))
    want = version_tuple(spec)
    return have[:len(want)] == want


def resolve_mode(ref: str) -> dict:
    name, _, spec = ref.partition("@")
    precedence = config().get("precedence", ["local", "org", "third-party"])
    candidates = [m for m in discover_modes()
                  if m["manifest"].get("name") == name
                  and version_matches(m["manifest"].get("version", "0.0.0"), spec or None)]
    if not candidates:
        raise PmosError(f"no registered mode matches '{ref}'. Run `pmos catalog` to see what's available.")

    def rank(m):
        src = precedence.index(m["source"]) if m["source"] in precedence else len(precedence)
        return (src, tuple(-x for x in version_tuple(m["manifest"]["version"])))

    return sorted(candidates, key=rank)[0]


def mode_skill_name(mode_name: str) -> str:
    return mode_name.replace("/", "-")


# --------------------------------------------------------------------------- validate
def cmd_validate(_args) -> int:
    errors, warnings = [], []
    role_sheet = {}
    try:
        raw = load_yaml(ROOT / config()["paths"]["roles"])
        validate_against(raw, "roles", "roles.yaml")
        role_sheet = raw["roles"]
    except PmosError as e:
        errors.append(str(e))

    skills = discover_skills()
    for sid, path in skills.items():
        meta, _ = frontmatter(path)
        expected = sid.replace("/", "-")
        if meta.get("name") != expected:
            errors.append(f"{rel(path)}: frontmatter name should be '{expected}' (got {meta.get('name')!r})")
        if not meta.get("description"):
            errors.append(f"{rel(path)}: missing description")

    agents_dir = ROOT / config()["paths"]["agents"]
    agent_names = set()
    for agent_md in sorted(agents_dir.glob("*.md")):
        meta, _ = frontmatter(agent_md)
        for key in ("name", "description", "tier", "grants"):
            if key not in meta:
                errors.append(f"{rel(agent_md)}: frontmatter missing '{key}'")
        if meta.get("tier") not in ("small", "mid", "top"):
            errors.append(f"{rel(agent_md)}: tier must be small, mid or top")
        agent_names.add(meta.get("name"))

    context_dir = ROOT / config()["paths"]["context"]
    for rname, r in role_sheet.items():
        if r.get("agent") not in agent_names:
            errors.append(f"roles.yaml/{rname}: agent '{r.get('agent')}' has no file in agents/")
        for s in r.get("skills", []):
            if s not in skills:
                errors.append(f"roles.yaml/{rname}: skill '{s}' not found under skills/")
        for c in r.get("context", []):
            if not (context_dir / c).exists():
                warnings.append(f"roles.yaml/{rname}: context file '{c}' not found in context/")

    seen = {}
    for m in discover_modes():
        man, where = m["manifest"], rel(m["path"])
        try:
            validate_against(man, "mode", where)
        except PmosError as e:
            errors.append(str(e))
            continue
        key = (man["name"], man["version"], m["source"])
        if key in seen:
            errors.append(f"{where}: duplicate of {seen[key]}")
        seen[key] = where
        skill_path = m["dir"] / man.get("skill", "SKILL.md")
        if not skill_path.exists():
            errors.append(f"{where}: skill file {rel(skill_path)} missing")
        else:
            meta, _ = frontmatter(skill_path)
            if meta.get("name") != mode_skill_name(man["name"]):
                errors.append(f"{rel(skill_path)}: frontmatter name should be '{mode_skill_name(man['name'])}'")
            if not meta.get("description"):
                errors.append(f"{rel(skill_path)}: missing description")
        for rname in [man["default_role"], *man.get("roles", [])]:
            if rname not in role_sheet:
                errors.append(f"{where}: role '{rname}' not in roles.yaml")
        for call in man.get("calls", []):
            try:
                resolve_mode(call)
            except PmosError:
                errors.append(f"{where}: calls '{call}', which is not registered")
        evals_dir = m["dir"] / man.get("evals", "evals/")
        if not list(evals_dir.glob("*.json")):
            errors.append(f"{where}: no golden tasks in {rel(evals_dir)} (no evals, no registration)")

    for w in warnings:
        print(f"warn: {w}")
    for e in errors:
        print(f"error: {e}")
    if errors:
        print(f"\n{len(errors)} error(s).")
        return 1
    print(f"OK: {len(seen)} mode(s), {len(role_sheet)} role(s), {len(skills)} shared skill(s), "
          f"{len(agent_names)} agent(s).")
    return 0


# --------------------------------------------------------------------------- catalog
def build_catalog() -> list[dict]:
    rows = []
    for m in discover_modes():
        man = m["manifest"]
        if not man.get("name"):
            continue
        rows.append({
            "name": man["name"],
            "version": man.get("version"),
            "summary": man.get("summary", ""),
            "accepts": man.get("accepts", {}),
            "verbs": man.get("verbs", []),
            "approval": man.get("approval"),
            "source": m["source"],
        })
    return sorted(rows, key=lambda r: r["name"])


def cmd_catalog(_args) -> int:
    rows = build_catalog()
    state = path_of("state")
    write_json(state / "catalog.json", rows)
    lines = [
        "# Mode catalog",
        "",
        f"Generated by `pmos catalog` at {now()}. The CoS picks modes from this list.",
        "",
        "| Mode | Version | Verbs | What it does | Accepts | Approval | Source |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in rows:
        accepts = ", ".join(f"{k}: {v}" for k, v in r["accepts"].items())
        lines.append(f"| `{r['name']}` | {r['version']} | {', '.join(r['verbs'])} | {r['summary']} "
                     f"| {accepts} | {r['approval']} | {r['source']} |")
    (state / "catalog.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{len(rows)} mode(s) -> {rel(state / 'catalog.md')}")
    return 0


# --------------------------------------------------------------------------- tasks
def tasks_dir() -> Path:
    return path_of("state") / "tasks"


def task_path(task_id: str) -> Path:
    return tasks_dir() / f"{task_id}.json"


def load_task(task_id: str) -> dict:
    p = task_path(task_id)
    if not p.exists():
        raise PmosError(f"no task {task_id}")
    return load_json(p)


def save_task(task: dict) -> None:
    task["updated_at"] = now()
    write_json(task_path(task["envelope"]["id"]), task)


def all_tasks() -> list[dict]:
    d = tasks_dir()
    if not d.exists():
        return []
    return [load_json(p) for p in sorted(d.glob("T-*.json"))]


def next_task_id() -> str:
    day = dt.datetime.now().strftime("%Y%m%d")
    taken = [int(p.stem.split("-")[2]) for p in tasks_dir().glob(f"T-{day}-*.json")] if tasks_dir().exists() else []
    return f"T-{day}-{(max(taken) + 1 if taken else 1):03d}"


def trace(task: dict, event: str, **fields) -> None:
    traces = path_of("traces")
    traces.mkdir(parents=True, exist_ok=True)
    env = task["envelope"]
    record = {
        "ts": now(), "event": event, "task_id": env["id"], "mode": env["mode"],
        "mode_version": task.get("mode_version"), "role": task.get("role"),
        "parent": env.get("parent"), **fields,
    }
    with open(traces / f"{dt.date.today():%Y-%m}.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


TYPE_CHECKS = {
    "string": lambda v: isinstance(v, str),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "bool": lambda v: isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "list": lambda v: isinstance(v, list),
    "object": lambda v: isinstance(v, dict),
}


def check_inputs(inputs: dict, accepts: dict, mode_name: str) -> None:
    problems = []
    for field, typ in accepts.items():
        optional = str(typ).endswith("?")
        base = str(typ).rstrip("?")
        if field not in inputs:
            if not optional:
                problems.append(f"missing required input '{field}' ({base})")
            continue
        check = TYPE_CHECKS.get(base)
        if check and not check(inputs[field]):
            problems.append(f"input '{field}' should be {base}")
    unknown = set(inputs) - set(accepts)
    if unknown:
        problems.append(f"unknown input(s) {sorted(unknown)}; {mode_name} accepts {sorted(accepts)}")
    if problems:
        raise PmosError(f"inputs don't match {mode_name}'s accepts:\n  - " + "\n  - ".join(problems))


def transition(task: dict, to: str, by: str, note: str | None = None) -> None:
    frm = task["state"]
    if to not in TRANSITIONS.get(frm, set()):
        allowed = ", ".join(sorted(TRANSITIONS.get(frm, set()))) or "none (terminal)"
        raise PmosError(f"{task['envelope']['id']}: can't move {frm} -> {to}. Allowed from {frm}: {allowed}")
    task["state"] = to
    task["history"].append({"ts": now(), "from": frm, "to": to, "by": by, "note": note})
    save_task(task)
    trace(task, "transition", **{"from": frm, "to": to, "by": by, "note": note})
    if to in TERMINAL and task["envelope"].get("parent"):
        maybe_wake_parent(task["envelope"]["parent"])


def maybe_wake_parent(parent_id: str) -> None:
    parent = load_task(parent_id)
    if parent["state"] != "waiting":
        return
    children = [load_task(c) for c in parent.get("children", [])]
    if children and all(c["state"] in TERMINAL for c in children):
        summary = ", ".join(f"{c['envelope']['id']}={c['state']}" for c in children)
        transition(parent, "queued", "pmos", f"children finished: {summary}")


def parse_inputs(raw: str) -> dict:
    if raw.startswith("@"):
        return load_json(Path(raw[1:]))
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise PmosError(f"--inputs is not valid JSON: {e}")
    if not isinstance(data, dict):
        raise PmosError("--inputs must be a JSON object")
    return data


def cmd_task_new(args) -> int:
    mode = resolve_mode(args.mode)
    man = mode["manifest"]
    inputs = parse_inputs(args.inputs)
    check_inputs(inputs, man.get("accepts", {}), man["name"])
    if man.get("verbs") and args.verb not in man["verbs"]:
        raise PmosError(f"{man['name']} supports verbs {man['verbs']}, not '{args.verb}'")
    role_name = args.role or man["default_role"]
    if role_name not in roles():
        raise PmosError(f"role '{role_name}' is not in roles.yaml")

    depth = 0
    parent = None
    if args.parent:
        parent = load_task(args.parent)
        depth = parent["envelope"].get("depth", 0) + 1
        max_depth = config()["defaults"].get("max_call_depth", 3)
        if depth > max_depth:
            raise PmosError(f"call depth {depth} exceeds max_call_depth {max_depth}")
        chain, cur = {man["name"]}, parent
        while cur:
            if cur["envelope"]["mode"].split("@")[0] in chain:
                raise PmosError(f"cycle: {man['name']} is already an ancestor of this task")
            chain.add(cur["envelope"]["mode"].split("@")[0])
            pid = cur["envelope"].get("parent")
            cur = load_task(pid) if pid else None

    defaults = config()["defaults"]["budget"]
    budget = {"max_usd": args.budget_usd if args.budget_usd is not None else defaults["max_usd"],
              "max_minutes": args.budget_minutes if args.budget_minutes is not None else defaults["max_minutes"]}
    if parent:  # children draw down the parent's budget
        pb = parent["envelope"].get("budget", defaults)
        budget = {k: min(budget[k], pb.get(k, budget[k])) for k in budget}

    tasks_dir().mkdir(parents=True, exist_ok=True)
    envelope = {
        "id": next_task_id(),
        "verb": args.verb,
        "mode": args.mode if "@" in args.mode else f"{man['name']}@{man['version']}",
        "role": role_name,
        "inputs": inputs,
        "acceptance": args.acceptance or [],
        "risk": args.risk or man.get("risk", "medium"),
        "approval": args.approval or man.get("approval", "none"),
        "budget": budget,
        "depends_on": args.depends_on or [],
        "parent": args.parent,
        "depth": depth,
        "reply_to": args.reply_to,
        "created_at": now(),
    }
    if args.workflow:
        envelope["workflow"] = args.workflow
    validate_against(envelope, "task", "envelope")
    for dep in envelope["depends_on"]:
        load_task(dep)

    task = {
        "envelope": envelope,
        "state": "queued",
        "mode_name": man["name"],
        "mode_version": man["version"],
        "mode_dir": rel(mode["dir"]),
        "role": role_name,
        "children": [],
        "revisions": 0,
        "approvals": [],
        "result": None,
        "result_path": None,
        "history": [{"ts": now(), "from": None, "to": "queued", "by": args.by, "note": args.note}],
    }
    save_task(task)
    trace(task, "created", by=args.by)
    if parent:
        parent["children"].append(envelope["id"])
        save_task(parent)
    write_board()
    print(envelope["id"])
    return 0


def deps_ready(task: dict) -> list[str]:
    return [d for d in task["envelope"].get("depends_on", []) if load_task(d)["state"] != "done"]


def cmd_task_show(args) -> int:
    task = load_task(args.id)
    if args.json:
        print(json.dumps(task, indent=2, ensure_ascii=False))
        return 0
    env = task["envelope"]
    mode = resolve_mode(f"{task['mode_name']}@{task['mode_version']}")
    man = mode["manifest"]
    role = roles()[task["role"]]
    skills = discover_skills()
    out = [
        f"# {env['id']} · {task['mode_name']}@{task['mode_version']} · {env['verb']} · state: {task['state']}",
        "",
        "## Envelope",
        "```json", json.dumps(env, indent=2, ensure_ascii=False), "```",
        "",
        "## Mode",
        f"- skill: {rel(mode['dir'] / man.get('skill', 'SKILL.md'))}",
        f"- approval: {env['approval']} · risk: {env['risk']}",
    ]
    if man.get("calls"):
        out.append(f"- may call: {', '.join(man['calls'])}")
    out += ["", f"## Role: {task['role']} (agent: {role['agent']}, tier: {role['tier']})",
            f"- persona: {role['persona']}"]
    for s in role.get("skills", []):
        out.append(f"- skill: {rel(skills[s]) if s in skills else s + ' (missing)'}")
    for c in role.get("context", []):
        out.append(f"- context: {rel(ROOT / config()['paths']['context'] / c)}")
    for extra in man.get("roles", []):
        out.append(f"- also uses role: {extra}")
    blocked_by = deps_ready(task)
    if blocked_by:
        out += ["", f"**Waiting on dependencies:** {', '.join(blocked_by)}"]
    if task["children"]:
        out += ["", "## Children"]
        for cid in task["children"]:
            c = load_task(cid)
            out.append(f"- {cid} · {c['mode_name']} · {c['state']}"
                       + (f" · result: {c['result_path']}" if c.get("result_path") else ""))
    out += ["", "## History"]
    for h in task["history"]:
        out.append(f"- {h['ts']} · {h['from'] or 'new'} -> {h['to']} · {h['by']}" + (f" · {h['note']}" if h.get("note") else ""))
    if task.get("result_path"):
        out += ["", f"## Result: {task['result_path']}", f"- status: {task['result']['status']}",
                f"- summary: {task['result']['summary']}"]
        for a in task["result"].get("artifacts", []):
            out.append(f"- artifact: {a['ref']}" + (f" ({a['title']})" if a.get("title") else ""))
        for a in task["result"].get("actions", []):
            out.append(f"- action: {a['system']}.{a['op']} · {a.get('preview', a['idempotency_key'])}")
    if args.for_review:
        baseline = (ROOT / "quality" / "baseline_rubric.md").read_text(encoding="utf-8")
        out += ["", "## Baseline rubric", baseline.strip(), "", "## Mode rubric"]
        out += [f"- {r}" for r in man.get("rubric", [])] or ["- (none)"]
        out += ["", "## Role rubric"]
        out += [f"- {r}" for r in role.get("rubric", [])] or ["- (none)"]
        if task.get("result"):
            out += ["", "## Producer self-check"]
            out += [f"- {'met' if s['met'] else 'NOT met'}: {s['criterion']}" + (f" · {s['note']}" if s.get("note") else "")
                    for s in task["result"].get("self_check", [])] or ["- (none recorded)"]
    print("\n".join(out))
    return 0


def cmd_task_move(args) -> int:
    task = load_task(args.id)
    if args.state == "running":
        pending = deps_ready(task)
        if pending:
            raise PmosError(f"{args.id} depends on unfinished task(s): {', '.join(pending)}")
    if args.state == "waiting":
        open_children = [c for c in task.get("children", []) if load_task(c)["state"] not in TERMINAL]
        if not open_children:
            raise PmosError(f"{args.id} has no unfinished children to wait for")
    if args.state == "revise":
        task["revisions"] = task.get("revisions", 0) + 1
    transition(task, args.state, args.by, args.note)
    write_board()
    print(f"{args.id}: {task['history'][-1]['from']} -> {args.state}")
    return 0


def cmd_task_result(args) -> int:
    task = load_task(args.id)
    if task["state"] != "running":
        raise PmosError(f"{args.id} is {task['state']}; submit results only while running "
                        f"(`pmos task move {args.id} running` first)")
    path = Path(args.file)
    result = load_json(path)
    validate_against(result, "result", rel(path.resolve()))
    if result["task_id"] != args.id:
        raise PmosError(f"result task_id {result['task_id']} != {args.id}")
    if "review" in result:
        raise PmosError("results must not include 'review'; the Reviewer writes it")
    if result["status"] == "blocked" and not result.get("open_questions"):
        raise PmosError("a blocked result needs at least one open_questions entry")
    missing = [a["ref"] for a in result.get("artifacts", [])
               if not re.match(r"^[a-z]+:", a["ref"]) and not (ROOT / a["ref"]).exists()]
    if missing:
        raise PmosError(f"artifact(s) not found: {', '.join(missing)}")
    keys = [a["idempotency_key"] for a in result.get("actions", [])]
    if len(keys) != len(set(keys)):
        raise PmosError("idempotency_key values must be unique within a result")

    task["result"] = result
    task["result_path"] = rel(path.resolve())
    to = {"done": "in_review", "needs_approval": "in_review", "blocked": "blocked", "failed": "failed"}[result["status"]]
    note = "; ".join(result.get("open_questions", [])) if to == "blocked" else result["summary"][:200]
    trace(task, "result", status=result["status"], actions=len(keys), usage=result.get("usage"))
    transition(task, to, args.by, note)
    write_board()
    print(f"{args.id}: result accepted -> {to}")
    return 0


def cmd_task_review(args) -> int:
    task = load_task(args.id)
    if task["state"] != "in_review":
        raise PmosError(f"{args.id} is {task['state']}, not in_review")
    passed = args.passed.lower() in ("true", "yes", "1", "pass")
    review = {"passed": passed, "notes": args.note or []}
    if args.score is not None:
        review["score"] = args.score
    task["result"]["review"] = review
    if task.get("result_path"):
        write_json(ROOT / task["result_path"], task["result"])
    trace(task, "review", passed=passed, score=args.score, by=args.by)
    env, result = task["envelope"], task["result"]
    if passed:
        needs_ok = env["approval"] != "none" and (result.get("actions") or env["approval"] == "before_publish")
        to = "awaiting_approval" if needs_ok else "done"
        note = f"review passed (score {args.score})"
    else:
        task["revisions"] = task.get("revisions", 0) + 1
        limit = config()["defaults"].get("max_revisions", 2)
        to = "revise" if task["revisions"] <= limit else "failed"
        note = "; ".join(args.note or []) or "review failed"
        if to == "failed":
            note = f"failed review {task['revisions']} times: {note}"
    transition(task, to, args.by, note)
    write_board()
    print(f"{args.id}: review {'passed' if passed else 'failed'} -> {to}")
    return 0


def cmd_task_approve(args) -> int:
    task = load_task(args.id)
    if task["state"] != "awaiting_approval":
        raise PmosError(f"{args.id} is {task['state']}, not awaiting_approval")
    actions = task["result"].get("actions", [])
    digest = hashlib.sha256(json.dumps(actions, sort_keys=True).encode()).hexdigest()[:16]
    task["approvals"].append({"ts": now(), "by": args.by, "note": args.note, "actions_sha": digest,
                              "actions": len(actions)})
    trace(task, "approved", by=args.by, actions=len(actions), actions_sha=digest)
    transition(task, "approved", args.by, args.note or f"approved {len(actions)} action(s)")
    write_board()
    print(f"{args.id}: approved ({len(actions)} action(s), sha {digest})")
    return 0


def cmd_task_list(args) -> int:
    rows = all_tasks()
    if args.state:
        rows = [t for t in rows if t["state"] == args.state]
    elif not args.all:
        rows = [t for t in rows if t["state"] not in TERMINAL]
    for t in rows:
        e = t["envelope"]
        print(f"{e['id']}  {t['state']:<17} {t['mode_name']:<24} {t['role']:<20} "
              f"{(t['history'][-1].get('note') or '')[:60]}")
    if not rows:
        print("(no tasks)")
    return 0


# --------------------------------------------------------------------------- board & decisions
def write_board() -> None:
    tasks = all_tasks()
    state = path_of("state")
    open_tasks = sorted([t for t in tasks if t["state"] not in TERMINAL],
                        key=lambda t: (OPEN_STATES.index(t["state"]), t["envelope"]["id"]))
    needs_pm = [t for t in open_tasks if t["state"] in ("awaiting_approval", "blocked")]
    recent = sorted([t for t in tasks if t["state"] in TERMINAL],
                    key=lambda t: t.get("updated_at", ""), reverse=True)[:10]
    lines = ["# Status board", "", f"Generated by pmos at {now()}. Read-only view; don't edit.", ""]
    lines += ["## Needs the PM", ""]
    if needs_pm:
        lines += ["| Task | Mode | State | Why |", "| --- | --- | --- | --- |"]
        for t in needs_pm:
            lines.append(f"| {t['envelope']['id']} | {t['mode_name']} | {t['state']} | "
                         f"{(t['history'][-1].get('note') or '').replace('|', '/')[:120]} |")
    else:
        lines.append("Nothing waiting on you.")
    lines += ["", "## Open", ""]
    if open_tasks:
        lines += ["| Task | Mode | Role | State | Parent | Updated |", "| --- | --- | --- | --- | --- | --- |"]
        for t in open_tasks:
            lines.append(f"| {t['envelope']['id']} | {t['mode_name']} | {t['role']} | {t['state']} | "
                         f"{t['envelope'].get('parent') or ''} | {t.get('updated_at', '')} |")
    else:
        lines.append("No open tasks.")
    lines += ["", "## Recently finished", ""]
    if recent:
        lines += ["| Task | Mode | State | Summary |", "| --- | --- | --- | --- |"]
        for t in recent:
            summary = (t.get("result") or {}).get("summary") or (t["history"][-1].get("note") or "")
            lines.append(f"| {t['envelope']['id']} | {t['mode_name']} | {t['state']} | "
                         f"{summary.replace('|', '/')[:120]} |")
    else:
        lines.append("None yet.")
    state.mkdir(parents=True, exist_ok=True)
    (state / "status.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def cmd_board(_args) -> int:
    write_board()
    print(rel(path_of("state") / "status.md"))
    return 0


def cmd_decide(args) -> int:
    log = ROOT / config()["paths"]["context"] / "decisions.log"
    with open(log, "a", encoding="utf-8") as f:
        f.write(f"{dt.date.today().isoformat()} · {args.text.strip()} · by {args.by}\n")
    print(f"appended to {rel(log)}")
    return 0


# --------------------------------------------------------------------------- render
def agent_defs() -> dict[str, tuple[dict, str, Path]]:
    out = {}
    for agent_md in sorted((ROOT / config()["paths"]["agents"]).glob("*.md")):
        meta, body = frontmatter(agent_md)
        out[meta["name"]] = (meta, body, agent_md)
    return out


def all_skill_sources() -> list[tuple[str, Path, Path | None]]:
    """(rendered skill name, SKILL.md path, mode dir or None)."""
    items = [(sid.replace("/", "-"), path, None) for sid, path in discover_skills().items()]
    for m in discover_modes():
        man = m["manifest"]
        items.append((mode_skill_name(man["name"]), m["dir"] / man.get("skill", "SKILL.md"), m["dir"]))
    return items


def render_claude_code() -> int:
    ad = config()["adapters"]["claude-code"]
    tiers = config()["tiers"][ad["provider"]]
    warnings = []

    claude_md = ROOT / "CLAUDE.md"
    if not claude_md.exists():
        claude_md.write_text("@AGENTS.md\n\n<!-- Generated by `pmos render claude-code`. "
                             "Edit AGENTS.md, not this file. -->\n", encoding="utf-8")
    elif "@AGENTS.md" not in claude_md.read_text(encoding="utf-8"):
        warnings.append("CLAUDE.md exists but doesn't import @AGENTS.md; add that line")

    agents_out = ROOT / ad["agents_dir"]
    agents_out.mkdir(parents=True, exist_ok=True)
    for name, (meta, body, _src) in agent_defs().items():
        if name == "cos":
            continue  # the CoS is the main session; it reads AGENTS.md via CLAUDE.md
        model = ad["aliases"][meta["tier"]] if ad.get("model_field", "alias") == "alias" else tiers[meta["tier"]]
        mapped, unmapped = [], []
        for g in meta.get("grants", []):
            tools = ad.get("grants_to_tools", {}).get(g)
            (mapped.extend(tools) if tools else unmapped.append(g))
        lines = ["---", f"name: {name}", f"description: {meta['description']}", f"model: {model}"]
        if unmapped:
            warnings.append(f"agent '{name}': grants {unmapped} have no tool mapping in pm-os.yaml; it inherits "
                            f"all tools, so the permission line is NOT enforced for it yet")
        else:
            lines.append(f"tools: {', '.join(dict.fromkeys(mapped))}")
        lines += ["---", "<!-- Generated by `pmos render claude-code` from "
                  f"{rel(_src)}. Edit the source, then re-render. -->", "", body.strip(), ""]
        (agents_out / f"{name}.md").write_text("\n".join(lines), encoding="utf-8")

    skills_out = ROOT / ad["skills_dir"]
    marker = skills_out / ".pmos-generated"
    if marker.exists():
        for old in marker.read_text(encoding="utf-8").split():
            shutil.rmtree(skills_out / old, ignore_errors=True)
    skills_out.mkdir(parents=True, exist_ok=True)
    names = []
    for name, skill_md, mode_dir in all_skill_sources():
        target = skills_out / name
        target.mkdir(parents=True, exist_ok=True)
        shutil.copy2(skill_md, target / "SKILL.md")
        if mode_dir is not None:
            shutil.copy2(mode_dir / "mode.yaml", target / "mode.yaml")
        names.append(name)
    marker.write_text("\n".join(names) + "\n", encoding="utf-8")

    for w in warnings:
        print(f"warn: {w}")
    print(f"claude-code: {len(agent_defs()) - 1} agent(s) -> {ad['agents_dir']}, "
          f"{len(names)} skill(s) -> {ad['skills_dir']}, CLAUDE.md -> AGENTS.md")
    return 0


def render_generic() -> int:
    ad = config()["adapters"]["generic"]
    tiers = config()["tiers"][ad["provider"]]
    out = ROOT / ad["out_dir"]
    out.mkdir(parents=True, exist_ok=True)
    skills = all_skill_sources()
    skill_index = ["## Skills available", "", "Load a skill by reading its SKILL.md when a step needs it.", ""]
    for name, path, _ in skills:
        meta, _ = frontmatter(path)
        skill_index.append(f"- `{name}` ({rel(path)}): {meta.get('description', '')}")
    models, tools = {"agents": {}, "roles": {}}, {}
    for name, (meta, body, _src) in agent_defs().items():
        if name == "cos":
            prompt = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        else:
            prompt = body.strip() + "\n\n" + "\n".join(skill_index)
        (out / f"{name}.system.md").write_text(prompt + "\n", encoding="utf-8")
        models["agents"][name] = {"tier": meta["tier"], "model": tiers.get(meta["tier"], "")}
        tools[name] = meta.get("grants", [])
    for rname, r in roles().items():
        models["roles"][rname] = {"agent": r["agent"], "tier": r["tier"], "model": tiers.get(r["tier"], "")}
    write_json(out / "models.json", models)
    write_json(out / "grants.json", tools)
    shutil.copy2(path_of("state") / "catalog.md", out / "catalog.md") if (path_of("state") / "catalog.md").exists() else None
    print(f"generic: {len(agent_defs())} system prompt(s), models.json, grants.json -> {ad['out_dir']}")
    return 0


def cmd_render(args) -> int:
    return {"claude-code": render_claude_code, "generic": render_generic}[args.adapter]()


# --------------------------------------------------------------------------- eval
def cmd_eval(args) -> int:
    modes = discover_modes()
    if args.modes:
        modes = [m for m in modes if m["manifest"].get("name") in args.modes]
    command = (config().get("eval") or {}).get("command") or ""
    out_root = ROOT / "build" / "evals"
    rendered = ran = 0
    for m in modes:
        man = m["manifest"]
        for case in sorted((m["dir"] / man.get("evals", "evals/")).glob("*.json")):
            spec = load_json(case)
            case_dir = out_root / man["name"].replace("/", "__") / case.stem
            case_dir.mkdir(parents=True, exist_ok=True)
            env = spec["envelope"]
            new_cmd = (f"python scripts/pmos.py task new --mode {env['mode']} --verb {env['verb']} "
                       f"--inputs '{json.dumps(env['inputs'])}' --risk {env.get('risk', 'medium')} "
                       f"--approval {env.get('approval', 'none')}"
                       + "".join(f" --acceptance {json.dumps(a)}" for a in env.get("acceptance", [])))
            fixtures = spec.get("fixtures", {})
            prompt = [
                f"# pm-os eval: {man['name']} · {spec.get('name', case.stem)}", "",
                "You are running a golden task in an isolated state directory.",
                "1. Create the task:", "", "```", new_cmd, "```", "",
                "2. Act as the `worker` agent (agents/worker.md) on the printed task id, end to end.",
                "   Where a step reads Jira or calendars, use the fixtures below instead of live systems.",
                "   Where a mode pauses for the PM (a gate), stop there.", "",
            ]
            if fixtures:
                prompt += ["## Fixtures", "", "```json", json.dumps(fixtures, indent=2), "```", ""]
            (case_dir / "prompt.md").write_text("\n".join(prompt), encoding="utf-8")
            grader = [f"# Grader: {man['name']} · {spec.get('name', case.stem)}", "",
                      "Score the worker's output (outputs/<task id>/) against each line. Pass = all met.", ""]
            grader += [f"- [ ] {e}" for e in spec.get("expect", [])]
            grader += ["", "Mode rubric:"] + [f"- [ ] {r}" for r in man.get("rubric", [])]
            (case_dir / "grader.md").write_text("\n".join(grader) + "\n", encoding="utf-8")
            rendered += 1
            if command:
                env_vars = {**os.environ,
                            "PMOS_STATE_DIR": str(case_dir / "state"),
                            "PMOS_TRACES_DIR": str(case_dir / "traces")}
                cmd = command.replace("{prompt_file}", str(case_dir / "prompt.md"))
                proc = subprocess.run(cmd, shell=True, cwd=ROOT, env=env_vars,
                                      capture_output=True, text=True, timeout=1800)
                (case_dir / "output.md").write_text(proc.stdout + ("\n\n[stderr]\n" + proc.stderr if proc.stderr else ""),
                                                    encoding="utf-8")
                ran += 1
                print(f"ran {man['name']}/{case.stem}: exit {proc.returncode}")
    print(f"{rendered} case(s) rendered to {rel(out_root)}" + (f", {ran} run" if command else
          " (set eval.command in pm-os.yaml to run them)"))
    return 0


# --------------------------------------------------------------------------- cli
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="pmos", description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("validate").set_defaults(fn=cmd_validate)
    sub.add_parser("catalog").set_defaults(fn=cmd_catalog)
    sub.add_parser("board").set_defaults(fn=cmd_board)

    d = sub.add_parser("decide")
    d.add_argument("text")
    d.add_argument("--by", default="cos")
    d.set_defaults(fn=cmd_decide)

    r = sub.add_parser("render")
    r.add_argument("adapter", choices=["claude-code", "generic"])
    r.set_defaults(fn=cmd_render)

    e = sub.add_parser("eval")
    e.add_argument("modes", nargs="*")
    e.set_defaults(fn=cmd_eval)

    t = sub.add_parser("task").add_subparsers(dest="task_cmd", required=True)
    n = t.add_parser("new")
    n.add_argument("--mode", required=True)
    n.add_argument("--verb", required=True, choices=["plan", "draft", "analyze", "execute", "review"])
    n.add_argument("--inputs", required=True, help="JSON object, or @path/to/inputs.json")
    n.add_argument("--role")
    n.add_argument("--workflow")
    n.add_argument("--risk", choices=["low", "medium", "high"])
    n.add_argument("--approval", choices=["none", "before_publish", "before_execute"])
    n.add_argument("--acceptance", action="append")
    n.add_argument("--depends-on", action="append", dest="depends_on")
    n.add_argument("--parent")
    n.add_argument("--budget-usd", type=float)
    n.add_argument("--budget-minutes", type=float)
    n.add_argument("--reply-to", default="cos")
    n.add_argument("--by", default="cos")
    n.add_argument("--note")
    n.set_defaults(fn=cmd_task_new)

    s = t.add_parser("show")
    s.add_argument("id")
    s.add_argument("--for-review", action="store_true")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_task_show)

    mv = t.add_parser("move")
    mv.add_argument("id")
    mv.add_argument("state", choices=sorted(TRANSITIONS))
    mv.add_argument("--note")
    mv.add_argument("--by", default="agent")
    mv.set_defaults(fn=cmd_task_move)

    rs = t.add_parser("result")
    rs.add_argument("id")
    rs.add_argument("file")
    rs.add_argument("--by", default="worker")
    rs.set_defaults(fn=cmd_task_result)

    rv = t.add_parser("review")
    rv.add_argument("id")
    rv.add_argument("--passed", required=True)
    rv.add_argument("--score", type=float)
    rv.add_argument("--note", action="append")
    rv.add_argument("--by", default="reviewer")
    rv.set_defaults(fn=cmd_task_review)

    ap = t.add_parser("approve")
    ap.add_argument("id")
    ap.add_argument("--by", required=True)
    ap.add_argument("--note")
    ap.set_defaults(fn=cmd_task_approve)

    ls = t.add_parser("list")
    ls.add_argument("--state", choices=sorted(TRANSITIONS))
    ls.add_argument("--all", action="store_true")
    ls.set_defaults(fn=cmd_task_list)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.fn(args)
    except PmosError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

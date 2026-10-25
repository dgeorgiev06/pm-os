#!/usr/bin/env python3
"""pmos — the deterministic core of pm-os. Harness- and model-neutral.

Every state change goes through this CLI, so any agent harness (or a human) can drive the
framework the same way. Later, the same functions become steps in a durable workflow engine.

  pmos validate                         check core, every installed pack, and their references
  pmos pack list                        installed packs
  pmos pack add PATH [--source S] [--approve-grants] [--upgrade [--force]] [--dry-run] [--with-golden]
  pmos pack remove NAME
  pmos pack path NAME                   an installed pack's directory (for pack scripts)
  pmos path NAME                        a configured path, e.g. outputs (PMOS_OUTPUTS_DIR applied)
  pmos catalog [--pack NAME]            write state/catalog.md + AGENTS.md; --pack prints one pack's modes
  pmos role show PACK/ROLE              a role's persona, skills, principles, context, rubric
  pmos task new --mode PACK/MODE [--verb V] --inputs JSON [--effort E] [--dispatch D] [--origin PACK:REF] [...]
  pmos task show ID [--for-review] [--checklist] [--json]
  pmos task move ID STATE [--note TEXT] [--by WHO]
  pmos task result ID RESULT.json
  pmos task review ID --verdicts FILE|- [--note TEXT ...]   per-line verdicts {id, pass, evidence, fix}; pmos computes pass
  pmos task approve ID --by WHO [--note TEXT]
  pmos task list [--state STATE] [--all]
  pmos task state ID [--json]           a task's state (full state JSON with --json), for scripts
  pmos action run ID [--key K]          run an approved task's actions through its pack's handlers
  pmos board                            regenerate state/status.md
  pmos decide "TEXT" [--by WHO]         append to context/decisions.log
  pmos stats [--mode PACK/MODE] [--json]   cost, latency, first-pass and revise-after-approval rates per mode and effort
  pmos render agents-md|claude-code|generic
  pmos eval [PACK | PACK/MODE ... | --all] [--kind conformance|golden|all] [--json] [--coverage] [--case GLOB]
                                        eval@1 cases per pack: conformance (code), then golden (model)
  pmos eval --framework [GROUP ...] [--case GLOB] [--json]   core's conformance cases (alias of `eval core`)
  pmos lint [PACK | DIR ...] [--json]   tightness: word budgets, mode step structure, filler, cite don't copy
  pmos cos-turn --started ISO [--replied ISO] --tool-calls N   log one CoS reply (pmos stats reports them)

Naming: modes are <pack>/<mode>; roles <pack>/<role>; skills and principles <pack>:<path>.
Inside a pack, a bare name means "this pack". Core resources belong to the pack "core".
Requires: Python 3.10+, PyYAML, jsonschema (pip install -r requirements.txt).
"""
from __future__ import annotations

import argparse
import datetime as dt
import fnmatch
import hashlib
import json
import math
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

try:
    import yaml
    import jsonschema
except ImportError:  # pragma: no cover
    sys.exit("pmos needs PyYAML and jsonschema: pip install -r requirements.txt")

ROOT = Path(__file__).resolve().parent.parent
CORE = "core"
TERMINAL = {"done", "failed"}
OPEN_STATES = ["queued", "running", "waiting", "in_review", "revise",
               "awaiting_approval", "approved", "blocked"]
GRANT_LEVEL = {"read": 1, "draft": 2, "write": 3}
APPROVAL_LEVEL = {"none": 0, "before_publish": 1, "before_execute": 2}   # a mode's approval is a floor
RISK_LEVEL = {"low": 0, "medium": 1, "high": 2}                        # so is its risk
EFFORT_LEVELS = ["low", "medium", "high", "max"]                     # how hard the model reasons
DISPATCH_VALUES = ["background", "foreground"]                      # how the CoS runs a subagent
SUMMARY_MAX_WORDS = 80      # the CoS forwards a result's summary as-is
REVIEW_PASS_SCORE = 4       # review passes when every core and must line holds and the should score is at least this

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
        return str(Path(path).resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


def render_name(ref: str) -> str:
    """pm:domain/prd-structure -> pm-domain-prd-structure; pm/prd -> pm-prd."""
    return re.sub(r"[:/]", "-", ref)


def with_skill_name(path: Path, name: str) -> str:
    """SKILL.md text with `name: <name>` in its frontmatter (authors may leave it out)."""
    text = path.read_text(encoding="utf-8")
    if not re.match(r"^---\s*\n", text):
        return f"---\nname: {name}\n---\n{text}"
    meta, _ = frontmatter(path)
    if "name" in meta:
        return text
    return re.sub(r"^---\s*\n", f"---\nname: {name}\n", text, count=1)


# --------------------------------------------------------------------------- config
_CACHE: dict = {}


def clear_cache() -> None:
    _CACHE.clear()


def config() -> dict:
    if "config" not in _CACHE:
        _CACHE["config"] = load_yaml(ROOT / "pm-os.yaml")
    return _CACHE["config"]


def path_of(key: str) -> Path:
    overrides = {"state": "PMOS_STATE_DIR", "traces": "PMOS_TRACES_DIR", "outputs": "PMOS_OUTPUTS_DIR"}
    env = overrides.get(key)
    if env and os.environ.get(env):
        return Path(os.environ[env]).resolve()
    return ROOT / config()["paths"][key]


def schema(name: str) -> dict:
    return load_json(ROOT / "contracts" / f"{name}.schema.json")


def schema_errors(data, schema_name: str, what: str) -> list[str]:
    validator = jsonschema.Draft202012Validator(schema(schema_name))
    out = []
    for e in sorted(validator.iter_errors(data), key=lambda e: list(e.path))[:10]:
        where = "/".join(str(p) for p in e.path) or "(root)"
        out.append(f"{what}: {where}: {e.message}")
    return out


def validate_against(data, schema_name: str, what: str) -> None:
    errs = schema_errors(data, schema_name, what)
    if errs:
        raise PmosError(f"does not match contracts/{schema_name}.schema.json:\n  - " + "\n  - ".join(errs))


# --------------------------------------------------------------------------- versions
def version_tuple(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in v.split("."))


def version_matches(version: str, spec: str | None) -> bool:
    """Supports exact (1.2.0), caret (^1 / ^1.2) and tilde (~1.2). ^0.x pins the minor."""
    if not spec:
        return True
    have = version_tuple(version)
    if spec.startswith("^"):
        want = version_tuple(spec[1:])
        floor = want + (0,) * (3 - len(want))
        if want[0] == 0 and len(want) > 1:
            return have[:2] == want[:2] and have >= floor
        return have[0] == want[0] and have >= floor
    if spec.startswith("~"):
        want = version_tuple(spec[1:])
        return have[:2] == (want + (0,))[:2] and have >= want + (0,) * (3 - len(want))
    want = version_tuple(spec)
    return have[:len(want)] == want


def split_ref(ref: str) -> tuple[str, str | None]:
    name, _, spec = ref.partition("@")
    return name, (spec or None)


# --------------------------------------------------------------------------- packs
def packs_file() -> Path:
    return ROOT / config()["paths"]["packs_file"]


def install_list() -> list[dict]:
    if "install" not in _CACHE:
        data = load_yaml(packs_file()) if packs_file().exists() else {}
        _CACHE["install"] = list((data or {}).get("packs", []))
    return _CACHE["install"]


def save_install_list(entries: list[dict]) -> None:
    header = ("# Installed packs. Managed by `pmos pack add` / `pmos pack remove`; read by the registry.\n"
              "# A pack appears here only after admission (valid manifests, evals present, exports respected)\n"
              "# and after its grants were approved with --approve-grants.\n")
    packs_file().write_text(header + yaml.safe_dump({"packs": entries}, sort_keys=False), encoding="utf-8")
    clear_cache()


def packs() -> dict[str, dict]:
    """name -> {name, dir, manifest, source, entry}. Always includes the core pack."""
    if "packs" not in _CACHE:
        out = {CORE: {"name": CORE, "dir": ROOT, "source": CORE, "entry": None,
                      "manifest": {"name": CORE, "version": config()["version"], "exports": None,
                                   "depends": []}}}
        for e in install_list():
            if not e.get("enabled", True):
                continue
            d = (ROOT / e["path"]).resolve() if not os.path.isabs(e["path"]) else Path(e["path"])
            man_path = d / "pack.yaml"
            if not man_path.exists():
                raise PmosError(f"packs.yaml lists '{e.get('name')}' at {e['path']}, but {rel(man_path)} is missing")
            man = load_yaml(man_path) or {}
            out[man.get("name", e.get("name"))] = {"name": man.get("name"), "dir": d, "manifest": man,
                                                  "source": e.get("source", "local"), "entry": e}
        _CACHE["packs"] = out
    return _CACHE["packs"]


def pack_paths(p: dict) -> dict[str, Path | None]:
    if p["name"] == CORE:
        c = config()["paths"]
        return {"skills": ROOT / c["skills"], "roles": ROOT / c["roles"],
                "agents": ROOT / c["agents"], "modes": None}
    d = p["dir"]
    return {"skills": d / "skills", "roles": d / "roles.yaml", "agents": d / "agents", "modes": d / "modes"}


def depends_on(pack: str) -> dict[str, str | None]:
    out = {}
    for dep in packs()[pack]["manifest"].get("depends", []) or []:
        name, spec = split_ref(dep)
        out[name] = spec
    return out


def is_exported(pack: str, kind: str, local: str) -> bool:
    if pack == CORE:
        return True
    exports = packs()[pack]["manifest"].get("exports") or {}
    names = exports.get(kind) or []
    if kind == "modes":  # exports.modes may be bare ("prd") or prefixed ("pm/prd")
        names = [q_role(n, pack) for n in names]
    if kind == "standards":  # exports.standards: "prd" or "standards/prd"
        names = [n.split("/")[-1] for n in names]
    return local in names


def visibility_error(owner: str | None, target: str, kind: str, local: str) -> str | None:
    """owner None = the CoS (top level): it may use anything a pack exports."""
    if target == CORE or owner == target:
        return None
    if target not in packs():
        return f"pack '{target}' is not installed"
    if owner not in (None, CORE) and target not in depends_on(owner):
        return f"pack '{owner}' uses {kind[:-1]} '{local}' from '{target}' without listing '{target}' in depends"
    if not is_exported(target, kind, local):
        return f"{kind[:-1]} '{local}' is internal to pack '{target}' (not in its exports)"
    return None


# --------------------------------------------------------------------------- channels (CH1-CH6)
def all_channels() -> dict[str, dict]:
    """'pack:channel/name' -> {ref, pack, name, dir, path, spec} for every installed pack's channels/."""
    out: dict[str, dict] = {}
    for pname, p in packs().items():
        if pname == CORE:
            continue
        for cfile in sorted((p["dir"] / "channels").glob("*/channel.yaml")):
            name = cfile.parent.name
            out[f"{pname}:channel/{name}"] = {"ref": f"{pname}:channel/{name}", "pack": pname, "name": name,
                                             "dir": cfile.parent, "path": cfile, "spec": load_yaml(cfile) or {}}
    return out


def channel_ref(ref: str, from_pack: str | None = None) -> str:
    """'pack:channel/name' as given; a bare 'channel/name' (or 'name') means the calling pack's own."""
    if ":" in ref:
        return ref
    if not from_pack:
        raise PmosError(f"channel '{ref}' needs its pack: write pack:channel/{ref.split('/')[-1]}")
    return f"{from_pack}:{ref if ref.startswith('channel/') else 'channel/' + ref}"


def can_see_channel(from_pack: str | None, ch: dict) -> bool:
    if from_pack is None or from_pack == ch["pack"]:
        return True
    return ch["pack"] in depends_on(from_pack) and is_exported(ch["pack"], "channels", ch["name"])


def resolve_channel(ref: str, from_pack: str | None = None) -> dict:
    full = channel_ref(ref, from_pack)
    chans = all_channels()
    if full not in chans:
        raise PmosError(f"unknown channel '{full}'; known channels: {', '.join(sorted(chans)) or 'none'}")
    ch = chans[full]
    if from_pack and from_pack != ch["pack"]:
        if ch["pack"] not in depends_on(from_pack):
            raise PmosError(f"pack '{from_pack}' uses channel '{full}' without listing '{ch['pack']}' in depends")
        if not is_exported(ch["pack"], "channels", ch["name"]):
            raise PmosError(f"channel '{full}' is internal to pack '{ch['pack']}' (not in its exports)")
    return ch


def channel_command(ch: dict) -> str:
    """The command the channel's send handler runs: its pack's actions: entry (script and fixed args)."""
    handler = ch["spec"]["send"]["handler"]
    actions = packs()[ch["pack"]]["manifest"].get("actions") or {}
    return actions.get(handler, "")


def text_words(text: str) -> int:
    """Whitespace tokens with a letter or digit, as lint counts them."""
    return sum(1 for t in text.split() if re.search(r"[A-Za-z0-9]", t))


def render_text(text: str, fmt: str) -> str:
    """Markdown in, the channel's format out (CH5)."""
    if fmt == "markdown":
        return text
    if fmt == "slack_mrkdwn":
        t = re.sub(r"\*\*(.+?)\*\*", r"*\1*", text)
        t = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", r"<\2|\1>", t)
        return re.sub(r"(?m)^#{1,6}\s+(.*)$", r"*\1*", t)
    t = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", r"\1 (\2)", text)
    t = re.sub(r"\*\*(.+?)\*\*", r"\1", t)
    t = re.sub(r"(?<![\w*])\*(?!\s)(.+?)\*(?!\w)", r"\1", t)
    t = re.sub(r"`([^`]+)`", r"\1", t)
    return re.sub(r"(?m)^#{1,6}\s+", "", t)


def channel_check(ch: dict, text: str, recipient: str | None = None) -> list[str]:
    """Limits and recipient rules of one channel (CH4). Empty = passes."""
    spec, problems = ch["spec"], []
    limits = spec.get("limits") or {}
    if "max_words" in limits and text_words(text) > limits["max_words"]:
        problems.append(f"max_words: {text_words(text)} words, over {ch['ref']}'s limit of {limits['max_words']}")
    if "max_chars" in limits and len(text) > limits["max_chars"]:
        problems.append(f"max_chars: {len(text)} characters, over {ch['ref']}'s limit of {limits['max_chars']}")
    pattern = spec["recipient"]["pattern"]
    if recipient is not None and not re.fullmatch(pattern, recipient):
        problems.append(f"recipient '{recipient}' is not a {spec['recipient']['type']} "
                        f"({ch['ref']} accepts /{pattern}/)")
    return problems


def channel_errors(name: str) -> list[str]:
    """Admission and validate checks for one pack's channels: schema, folder name, handler, pattern, exports."""
    p = packs()[name]
    man, actions = p["manifest"], p["manifest"].get("actions") or {}
    errors, names = [], set()
    for cfile in sorted((p["dir"] / "channels").glob("*/channel.yaml")):
        where, spec = rel(cfile), load_yaml(cfile) or {}
        names.add(cfile.parent.name)
        errors += schema_errors(spec, "channel", where)
        if spec.get("name") != cfile.parent.name:
            errors.append(f"{where}: name '{spec.get('name')}' must equal its folder ({cfile.parent.name})")
        handler = (spec.get("send") or {}).get("handler")
        if handler and handler not in actions:
            errors.append(f"{where}: send.handler '{handler}' is not an actions: entry of {rel(p['dir'] / 'pack.yaml')}")
        pattern = ((spec.get("recipient") or {}).get("pattern")) or ""
        try:
            re.compile(pattern)
        except re.error as e:
            errors.append(f"{where}: recipient.pattern is not a regular expression ({e})")
    for ch in (man.get("exports") or {}).get("channels") or []:
        if ch not in names:
            errors.append(f"{rel(p['dir'] / 'pack.yaml')}: exports channel '{ch}', which the pack doesn't contain")
    return errors


def read_text_arg(path: str) -> str:
    return sys.stdin.read() if path == "-" else Path(path).read_text(encoding="utf-8")


def cmd_channel_show(args) -> int:
    if not args.ref:
        rows = [c for c in all_channels().values() if can_see_channel(args.from_pack, c)]
        if args.json:
            print(json.dumps([{"ref": c["ref"], "format": c["spec"]["format"], "system": c["spec"]["system"]}
                              for c in rows], indent=2))
        else:
            for c in rows:
                print(f"{c['ref']}  {c['spec']['format']}  {c['spec']['system']}  {c['spec']['summary']}")
        if not rows:
            print("(no channels)")
        return 0
    ch = resolve_channel(args.ref, args.from_pack)
    spec = ch["spec"]
    info = {"ref": ch["ref"], "pack": ch["pack"], "name": ch["name"], "dir": rel(ch["dir"]),
            "system": spec["system"], "format": spec["format"], "limits": spec.get("limits") or {},
            "recipient": spec["recipient"], "send": {"handler": spec["send"]["handler"], "command": channel_command(ch)}}
    if args.json:
        print(json.dumps(info, indent=2, ensure_ascii=False))
    else:
        print(f"{ch['ref']}: {spec['format']}, {spec['system']}, limits {info['limits'] or 'none'}, "
              f"recipient {spec['recipient']['type']} /{spec['recipient']['pattern']}/, sends via {info['send']['handler']}")
    return 0


def cmd_channel_check(args) -> int:
    ch = resolve_channel(args.ref, args.from_pack)
    text = read_text_arg(args.text)
    problems = channel_check(ch, text, args.recipient)
    if problems:
        for pr in problems:
            print(f"error: {pr}", file=sys.stderr)
        return 1
    print(f"ok: {ch['ref']}: {text_words(text)} words, {len(text)} characters")
    return 0


def cmd_channel_render(args) -> int:
    ch = resolve_channel(args.ref, args.from_pack)
    print(render_text(read_text_arg(args.text), ch["spec"]["format"]))
    return 0


# --------------------------------------------------------------------------- registry
def all_skills() -> dict[str, Path]:
    """'<pack>:<path>' -> SKILL.md, for skills and principles of every installed pack."""
    if "skills" not in _CACHE:
        out = {}
        for name, p in packs().items():
            base = pack_paths(p)["skills"]
            if base and base.exists():
                for skill_md in sorted(base.rglob("SKILL.md")):
                    out[f"{name}:{skill_md.parent.relative_to(base).as_posix()}"] = skill_md
        _CACHE["skills"] = out
    return _CACHE["skills"]


def all_standards() -> dict[str, Path]:
    """'<pack>:standards/<name>' -> standards/<name>.yaml, for every installed pack (core has none)."""
    if "standards" not in _CACHE:
        out = {}
        for name, p in packs().items():
            d = p["dir"] / "standards" if name != CORE else None
            for f in sorted(d.glob("*.yaml")) if d and d.is_dir() else []:
                out[f"{name}:standards/{f.stem}"] = f
        _CACHE["standards"] = out
    return _CACHE["standards"]


def q_standard(ref: str, owner: str) -> str:
    """prd / standards/prd (inside pack OWNER) or pm:standards/prd -> pm:standards/prd."""
    pack, _, local = ref.partition(":") if ":" in ref else (owner, "", ref)
    return f"{pack}:{local if local.startswith('standards/') else 'standards/' + local}"


def load_standard(sid: str) -> dict | None:
    path = all_standards().get(sid)
    if not path:
        return None
    try:
        data = load_yaml(path)
    except yaml.YAMLError:
        return None
    return data if isinstance(data, dict) else None


def mode_standard(man: dict, pack: str) -> dict | None:
    """A mode's `standard:` as {ref (qualified), output (or None when it can't be told), data (or None)}.
    The string form applies to the mode's only doc_ref output."""
    raw = man.get("standard")
    if not raw:
        return None
    if isinstance(raw, dict):
        ref, output = str(raw.get("ref") or ""), raw.get("output")
    else:
        ref = str(raw)
        docs = [k for k, t in (man.get("returns") or {}).items() if str(t).rstrip("?") == "doc_ref"]
        output = docs[0] if len(docs) == 1 else None
    sid = q_standard(ref, pack)
    return {"ref": sid, "output": output, "data": load_standard(sid)}


def standard_output_ok(man: dict, output: str | None) -> bool:
    return bool(output) and str((man.get("returns") or {}).get(output, "")).rstrip("?") == "doc_ref"


def known_products() -> dict[str, list[str]]:
    """product -> the installed packs that declare an overlay for it (pack.yaml `overlays:`)."""
    out: dict[str, list[str]] = {}
    for name, p in packs().items():
        for product in (p["manifest"].get("overlays") or {}) if name != CORE else []:
            out.setdefault(product, []).append(name)
    return out


def context_product_file() -> Path:
    return ROOT / config()["paths"]["context"] / "product.md"


def resolve_product(flag: str | None, parent: dict | None, pack: str) -> dict:
    """The task's product and its overlay skills: --product, else the parent's, else `product:` in
    context/product.md's frontmatter. Unknown products are refused; a product from context is ignored
    when no installed pack declares overlays (products don't apply there)."""
    known = known_products()
    if flag:
        product, source = flag, "flag"
    elif parent and parent.get("product"):
        product, source = parent["product"], "parent"
    else:
        meta = frontmatter(context_product_file())[0] if context_product_file().exists() else {}
        product, source = (str(meta.get("product") or "").strip() or None), "context"
        if product and not known:
            product = None
    if not product:
        return {"product": None, "product_source": None, "overlay_skills": []}
    if product not in known:
        where = {"flag": "--product", "parent": "the parent task",
                 "context": f"{rel(context_product_file())} (frontmatter product:)"}[source]
        raise PmosError(f"unknown product '{product}' (from {where}); known products, from the packs' overlays: "
                        f"{', '.join(sorted(known)) or 'none'}")
    overlay = (packs()[pack]["manifest"].get("overlays") or {}).get(product) or [] if pack != CORE else []
    return {"product": product, "product_source": source,
            "overlay_skills": list(dict.fromkeys(q_skill(s, pack) for s in overlay))}


def all_principles() -> dict[str, dict]:
    """'<pack>:<name>' -> {path, meta, pack}. A principle is a skill under principles/."""
    out = {}
    for sid, path in all_skills().items():
        pack, _, local = sid.partition(":")
        if local.startswith("principles/") and local.count("/") == 1:
            meta, _ = frontmatter(path)
            out[f"{pack}:{local.split('/', 1)[1]}"] = {"path": path, "meta": meta, "pack": pack}
    return out


def all_roles() -> dict[str, dict]:
    """'<pack>/<role>' -> role dict (+ _pack, _name)."""
    if "roles" not in _CACHE:
        out = {}
        for name, p in packs().items():
            f = pack_paths(p)["roles"]
            if f and f.exists():
                for rname, r in ((load_yaml(f) or {}).get("roles") or {}).items():
                    out[f"{name}/{rname}"] = {**r, "_pack": name, "_name": rname}
        _CACHE["roles"] = out
    return _CACHE["roles"]


def all_agents() -> dict[str, tuple[dict, str, Path, str]]:
    """agent name -> (frontmatter, body, path, pack)."""
    out = {}
    for name, p in packs().items():
        d = pack_paths(p)["agents"]
        if d and d.exists():
            for agent_md in sorted(d.glob("*.md")):
                meta, body = frontmatter(agent_md)
                out[meta.get("name", agent_md.stem)] = (meta, body, agent_md, name)
    return out


def discover_modes() -> list[dict]:
    if "modes" not in _CACHE:
        out = []
        for name, p in packs().items():
            d = pack_paths(p)["modes"]
            if not d or not d.exists():
                continue
            for manifest in sorted(d.glob("*/mode.yaml")):
                out.append({"manifest": load_yaml(manifest) or {}, "dir": manifest.parent, "path": manifest,
                            "pack": name, "source": p["source"]})
        _CACHE["modes"] = out
    return _CACHE["modes"]


def q_role(ref: str, owner: str) -> str:
    return ref if "/" in ref else f"{owner}/{ref}"


def q_skill(ref: str, owner: str) -> str:
    return ref if ":" in ref else f"{owner}:{ref}"


def resolve_mode(ref: str, from_pack: str | None = None, check_visibility: bool = True) -> dict:
    name, spec = split_ref(ref)
    precedence = config().get("precedence", ["local", "org", "third-party"])
    candidates = [m for m in discover_modes()
                  if m["manifest"].get("name") == name
                  and version_matches(m["manifest"].get("version", "0.0.0"), spec)]
    if not candidates:
        raise PmosError(f"no installed mode matches '{ref}'. `pmos catalog` lists what's available.")

    def rank(m):
        src = precedence.index(m["source"]) if m["source"] in precedence else len(precedence)
        return (src, tuple(-x for x in version_tuple(m["manifest"]["version"])))

    mode = sorted(candidates, key=rank)[0]
    if check_visibility:
        err = visibility_error(from_pack, mode["pack"], "modes", name)
        if err:
            raise PmosError(err)
    return mode


def resolve_role(ref: str, owner: str) -> dict:
    fq = q_role(ref, owner)
    role = all_roles().get(fq)
    if not role:
        raise PmosError(f"role '{fq}' not found")
    err = visibility_error(owner, role["_pack"], "roles", role["_name"])
    if err:
        raise PmosError(err)
    return role


def approved_grants(pack: str) -> dict[str, str]:
    entry = packs()[pack].get("entry") or {}
    return entry.get("grants_approved") or {}


def grant_excess(mode: dict) -> dict[str, tuple[str, str | None]]:
    """system -> (requested, approved) for every grant a mode asks for beyond its pack's approval."""
    if mode["pack"] == CORE:
        return {}
    approved = approved_grants(mode["pack"])
    out = {}
    for system, level in (mode["manifest"].get("grants") or {}).items():
        if GRANT_LEVEL.get(level, 0) > GRANT_LEVEL.get(approved.get(system), 0):
            out[system] = (level, approved.get(system))
    return out


def grant_excess_message(mode: dict) -> str:
    excess = grant_excess(mode)
    parts = ", ".join(f"{s}: {req} (approved: {appr or 'none'})" for s, (req, appr) in excess.items())
    pack = mode["pack"]
    return (f"mode {mode['manifest']['name']} requests grants its pack's approval doesn't cover: {parts}. "
            f"Bump {pack}'s version and run `pmos pack add {rel(packs()[pack]['dir'])} --upgrade --approve-grants`.")


# --------------------------------------------------------------------------- settings: effort, dispatch
def agent_meta(name: str | None) -> dict:
    agent = all_agents().get(name or "")
    return agent[0] if agent else {}


def resolve_setting(key: str, flag: str | None, man: dict | None, role: dict | None) -> tuple[str, str]:
    """(value, source) for a per-task setting: the task flag > mode.yaml > role > the role's agent >
    `defaults.<key>` in pm-os.yaml. Used for `effort` and `dispatch`."""
    if flag:
        return flag, "flag"
    for source, holder in (("mode", man or {}), ("role", role or {}), ("agent", agent_meta((role or {}).get("agent")))):
        if holder.get(key):
            return holder[key], source
    fallback = {"effort": "medium", "dispatch": "background"}[key]
    return (config().get("defaults") or {}).get(key) or fallback, "default"


def effort_bounds() -> tuple[int, int]:
    b = config().get("effort") or {}
    return EFFORT_LEVELS.index(b.get("min", "low")), EFFORT_LEVELS.index(b.get("max", "max"))


def risk_scaled(level: str, risk: str) -> tuple[str, int]:
    """LEVEL moved one step up for risk high and one down for risk low, clamped by effort.min/max."""
    adjust = {"high": 1, "low": -1}.get(risk, 0)
    lo, hi = effort_bounds()
    i = min(max(EFFORT_LEVELS.index(level) + adjust, lo), hi)
    return EFFORT_LEVELS[i], adjust


def resolve_effort(flag: str | None, man: dict | None, role: dict | None, risk: str) -> dict:
    """The effort a task runs at. An explicit --effort is used as given; anything else is risk-scaled."""
    base, source = resolve_setting("effort", flag, man, role)
    level, adjust = (base, 0) if source == "flag" else risk_scaled(base, risk)
    return {"effort": level, "effort_source": source, "effort_base": base, "effort_risk_adjust": adjust}


def review_effort(risk: str) -> str:
    """The Reviewer's effort for a task: core/reviewer's (role > agent > default, high), one level lower for a
    low-risk task. Risk high never raises it (a high-risk review stays at the reviewer's level); clamped by
    effort.min/max."""
    role = all_roles().get(f"{CORE}/reviewer") or {"agent": "reviewer"}
    base, _ = resolve_setting("effort", None, None, role)
    lo, hi = effort_bounds()
    i = EFFORT_LEVELS.index(base) - (1 if risk == "low" else 0)
    return EFFORT_LEVELS[min(max(i, lo), hi)]


def effort_param(provider: str, level: str) -> tuple[str | None, str]:
    """The provider's parameter name and value for LEVEL, from effort_map in pm-os.yaml."""
    m = (config().get("effort_map") or {}).get(provider) or {}
    return m.get("param"), str(m.get(level, level))


# --------------------------------------------------------------------------- definition of done
CODE_PLACEHOLDER = re.compile(r"\{([^{}\s]*)\}")     # {outputs.prd}, {inputs.plan}, {task}, {outputs_dir}
CHECKLIST_ORDER = {"core": 0, "must": 1, "code": 2, "should": 3}


def standard_lines(man: dict, pack: str) -> list[dict]:
    """The must lines a mode's `standard:` adds: the code line `standard` (check_doc.py on the output) and
    one judged line per `judgment:` entry of the standard (standard-1, …)."""
    std = mode_standard(man, pack)
    if not std:
        return []
    out = []
    if standard_output_ok(man, std["output"]):
        cmd = f"python scripts/check_doc.py --standard {std['ref']} {{outputs.{std['output']}}}"
        out.append({"id": "standard", "kind": "code", "section": "must", "text": f"`{cmd}` exits 0",
                    "command": cmd, "timeout": None, "source": "standard"})
    for i, line in enumerate((std["data"] or {}).get("judgment") or [], 1):
        out.append({"id": f"standard-{i}", "kind": "must", "section": "must", "text": str(line), "source": "standard"})
    return out


def done_lines(man: dict, pack: str) -> list[dict]:
    """The mode's definition of done as lines {id, kind: must|code|should, text, command?, timeout?,
    principle?, source?}: the lines its `standard:` adds (source: standard), then its `done:` block.
    Ids: an explicit `id`, else must-N / should-N for judged lines, code-N for code lines, and the
    principle's qualified ref for a cited principle."""
    principles, out = all_principles(), standard_lines(man, pack)
    for section in ("must", "should"):
        n_text = n_code = 0
        for raw in (man.get("done") or {}).get(section) or []:
            raw = {"text": raw} if isinstance(raw, str) else dict(raw or {})
            if "code" in raw:
                n_code += 1
                out.append({"id": raw.get("id") or f"code-{n_code}", "kind": "code", "section": section,
                            "text": f"`{raw['code']}` exits 0", "command": str(raw["code"]), "timeout": raw.get("timeout")})
            elif "principle" in raw:
                pid = q_skill(str(raw["principle"]), pack)
                pr = principles.get(pid)
                out.append({"id": raw.get("id") or pid, "kind": section, "section": section, "principle": pid,
                            "text": pr["meta"].get("check", pid) if pr else f"principle {pid}"})
            else:
                n_text += 1
                out.append({"id": raw.get("id") or f"{section}-{n_text}", "kind": section, "section": section,
                            "text": str(raw.get("text", ""))})
    return out


def code_script(command: str) -> str | None:
    """The script a code line runs: the first argument after python/python3, else the command itself."""
    try:
        tokens = shlex.split(CODE_PLACEHOLDER.sub("X", command))
    except ValueError:
        return None
    if tokens and Path(tokens[0]).name in ("python", "python3"):
        tokens = tokens[1:]
    return tokens[0] if tokens and not tokens[0].startswith("-") else None


def script_path(script: str, pack: str) -> Path:
    """A code line's script on disk: `packs/<pack>/…` means the pack's own folder, wherever it is installed."""
    prefix = f"packs/{pack}/"
    if pack != CORE and script.startswith(prefix):
        return packs()[pack]["dir"] / script[len(prefix):]
    return ROOT / script


def done_errors(mm: dict, where: str, pack: str) -> list[str]:
    """The checks `validate` and admission make on a mode's done block (the schema is checked first)."""
    errors, ids, principles = [], {}, all_principles()
    returns = {k for k in (mm.get("returns") or {})}
    accepts = {k for k in (mm.get("accepts") or {})}
    pack_scripts = set(view_scripts(pack_view(pack))) if pack != CORE else set()
    for line in done_lines(mm, pack):
        lid = line["id"]
        if lid in ids:
            errors.append(f"{where}: done: two lines have the id '{lid}'; give one an explicit id")
        ids[lid] = True
        if line.get("principle"):
            pid = line["principle"]
            if pid not in principles:
                errors.append(f"{where}: done: principle '{pid}' not found")
            else:
                err = visibility_error(pack, pid.split(":")[0], "principles", pid.split(":", 1)[1])
                if err:
                    errors.append(f"{where}: done: {err}")
        if line["kind"] != "code":
            continue
        cmd = line["command"]
        if line["section"] != "must":
            errors.append(f"{where}: done.should: code line '{cmd}' belongs in done.must (pmos runs code lines as musts)")
        for name in CODE_PLACEHOLDER.findall(cmd):
            kind, _, field = name.partition(".")
            if name in ("task", "outputs_dir"):
                continue
            if kind == "outputs" and field:
                if field not in returns:
                    errors.append(f"{where}: done: code line '{cmd}': {{{name}}} names no output in returns "
                                  f"({', '.join(sorted(returns)) or 'none'})")
            elif kind == "inputs" and field:
                if field not in accepts:
                    errors.append(f"{where}: done: code line '{cmd}': {{{name}}} names no input in accepts")
            else:
                errors.append(f"{where}: done: code line '{cmd}': unknown placeholder {{{name}}}; use {{outputs.<name>}}, "
                              f"{{inputs.<name>}}, {{task}} or {{outputs_dir}}")
        script = code_script(cmd)
        if not script or "{" in script:
            errors.append(f"{where}: done: code line '{cmd}' runs no script file (a code line runs a pack or core script)")
            continue
        path = script_path(script, pack)
        if not path.is_file():
            errors.append(f"{where}: done: code line '{cmd}': script {script} not found")
            continue
        p = packs()[pack]
        in_pack = pack != CORE and path.resolve().is_relative_to(p["dir"].resolve()) and \
            path.resolve().relative_to(p["dir"].resolve()).as_posix() in pack_scripts
        in_core = path.resolve().parent == (ROOT / "scripts").resolve() and path.suffix == ".py"
        if not (in_pack or in_core):
            errors.append(f"{where}: done: code line '{cmd}': {script} is not one of the pack's scripts (scripts/, "
                          f"modes/*/scripts/) or core's scripts/, so no conformance case covers it")
    return errors


def fill_code(line: dict, task: dict, result: dict) -> tuple[str, list[str]]:
    """A code line's command with its placeholders filled from the task and its result (values shell-quoted),
    and the names it couldn't fill."""
    env, missing = task["envelope"], []
    outputs = result.get("outputs") or {}
    inputs = task.get("inputs_resolved") or env.get("inputs") or {}
    out_dir = path_of("outputs") / env["id"]

    def value(v) -> str:
        return shlex.quote(v if isinstance(v, str) else json.dumps(v, ensure_ascii=False))

    def sub(m):
        name = m.group(1)
        if name == "task":
            return env["id"]
        if name == "outputs_dir":
            return shlex.quote(rel(out_dir))
        kind, _, field = name.partition(".")
        source = {"outputs": outputs, "inputs": inputs}.get(kind)
        if source is None or field not in source:
            missing.append(name)
            return m.group(0)
        return value(source[field])
    cmd = CODE_PLACEHOLDER.sub(sub, line["command"])
    pack = task.get("pack")
    if pack and pack != CORE and pack in packs():     # packs/<pack>/… is the pack's folder, wherever installed
        actual = rel(packs()[pack]["dir"])
        if actual != f"packs/{pack}":
            cmd = re.sub(rf"(?<![\w/.-])packs/{re.escape(pack)}/", actual + "/", cmd)
    return cmd, missing


def run_code_lines(task: dict, result: dict) -> list[dict]:
    """Run the mode's done.must code lines for a result, in the repo root, each under its timeout."""
    recs = []
    default_timeout = int((config().get("defaults") or {}).get("code_timeout_seconds") or 120)
    for line in [ln for ln in done_lines(task_manifest(task), task.get("pack") or CORE) if ln["kind"] == "code"]:
        cmd, missing = fill_code(line, task, result)
        started = time.time()
        rec = {"id": line["id"], "command": cmd}
        if missing:
            rec.update(exit=None, passed=False,
                       output=f"not run: the result has no {', '.join('{' + n + '}' for n in missing)}")
        else:
            timeout = int(line.get("timeout") or default_timeout)
            run = re.sub(r"^python3?(?=\s)", shlex.quote(sys.executable), cmd)
            try:
                proc = subprocess.run(run, shell=True, cwd=ROOT, capture_output=True, text=True, timeout=timeout,
                                      env={**os.environ, "PMOS_ROOT": str(ROOT)})
                rec.update(exit=proc.returncode, passed=proc.returncode == 0,
                           output=(proc.stdout + ("\n" if proc.stdout and proc.stderr else "") + proc.stderr).strip())
            except subprocess.TimeoutExpired:
                rec.update(exit=None, passed=False, output=f"timed out after {timeout} s")
        rec["pass"] = rec.pop("passed")
        rec["output"] = rec["output"][-2000:]
        rec["seconds"] = round(time.time() - started, 2)
        recs.append(rec)
    return recs


def tail(text: str, n: int = 300) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= n else "…" + text[-n:]


def principles_for(mode: dict, role: dict) -> list[tuple[str, str, dict]]:
    """(group, id, principle) for core 'always' principles, then the mode's, then the role's."""
    principles = all_principles()
    out, seen = [], set()
    for pid, pr in sorted(principles.items()):
        if pr["pack"] == CORE and pr["meta"].get("always"):
            out.append(("core", pid, pr))
            seen.add(pid)
    for group, refs, owner in (("mode", mode["manifest"].get("principles", []), mode["pack"]),
                               ("role", role.get("principles", []), role["_pack"])):
        for ref in refs or []:
            pid = q_skill(ref, owner)
            if pid in seen or pid not in principles:
                continue
            out.append((group, pid, principles[pid]))
            seen.add(pid)
    return out


# --------------------------------------------------------------------------- validate
def skill_ref_errors(where: str, ref: str, owner: str) -> list[str]:
    """A skill reference (a role's, a mode's or an overlay's): it exists and OWNER may see it."""
    sid = q_skill(ref, owner)
    if sid not in all_skills():
        return [f"{where}: skill '{sid}' not found"]
    err = visibility_error(owner, sid.split(":")[0], "skills", sid.split(":", 1)[1])
    return [f"{where}: {err}"] if err else []


def standard_file_errors(pack_dir: Path) -> list[str]:
    """Each standards/<name>.yaml matches contracts/standard.schema.json, is named after its file, has
    distinct section ids and forbid patterns that compile."""
    errors = []
    d = pack_dir / "standards"
    for f in sorted(d.glob("*.yaml")) if d.is_dir() else []:
        where = rel(f)
        try:
            data = load_yaml(f)
        except yaml.YAMLError as e:
            errors.append(f"{where}: standard is not valid YAML: {str(e).splitlines()[0]}")
            continue
        errs = schema_errors(data, "standard", f"{where} (standard)")
        if errs:
            errors += errs
            continue
        if data["name"] != f.stem:
            errors.append(f"{where}: standard name '{data['name']}' must match its file name ('{f.stem}')")
        ids = [s["id"] for s in data["sections"]]
        errors += [f"{where}: standard has two sections with the id '{i}'" for i in sorted({i for i in ids if ids.count(i) > 1})]
        for rule in data.get("forbid") or []:
            try:
                re.compile(rule["pattern"])
            except re.error as e:
                errors.append(f"{where}: forbid '{rule['id']}': pattern doesn't compile ({e})")
    return errors


def mode_standard_errors(mm: dict, where: str, pack: str) -> list[str]:
    std = mode_standard(mm, pack)
    if not std:
        return []
    errors, sid = [], std["ref"]
    if sid not in all_standards():
        errors.append(f"{where}: standard {sid} not found (a standard is packs/<pack>/standards/<name>.yaml)")
    else:
        target, local = sid.split(":")[0], sid.split("/")[-1]
        err = visibility_error(pack, target, "standards", local)
        if err:
            errors.append(f"{where}: {sid}: {err}")
        elif std["data"] is None:
            errors.append(f"{where}: standard {sid} can't be read")
    if not standard_output_ok(mm, std["output"]):
        docs = [k for k, t in (mm.get("returns") or {}).items() if str(t).rstrip("?") == "doc_ref"]
        errors.append(f"{where}: standard: output '{std['output'] or '?'}' is not a doc_ref output in returns "
                      f"(doc_ref outputs: {', '.join(docs) or 'none'}); write standard: {{ref, output}}")
    return errors


def principle_once_errors(mm: dict, where: str, pack: str) -> list[str]:
    """A principle is cited once per task: document-type principles on the mode, voice and style on the
    role. A mode (principles or done lines) and its default role citing the same one is an error."""
    try:
        role = resolve_role(mm["default_role"], pack)
    except PmosError:
        return []      # reported with the role checks
    mine = {q_skill(x, pack) for x in mm.get("principles") or []}
    mine |= {ln["principle"] for ln in done_lines(mm, pack) if ln.get("principle")}
    theirs = {q_skill(x, role["_pack"]) for x in role.get("principles") or []}
    return [f"{where}: mode {mm['name']} and its default role {role['_pack']}/{role['_name']} both cite principle "
            f"{pid}; cite it once (document-type principles on the mode, voice and style on the role)"
            for pid in sorted(mine & theirs)]


def check_pack(name: str, check_grants: bool = True) -> tuple[list[str], list[str]]:
    """Errors and warnings for one installed pack (including core). Admission passes
    check_grants=False, because grants are approved after the structural checks pass."""
    errors, warnings = [], []
    p = packs()[name]
    man = p["manifest"]
    paths = pack_paths(p)
    where_pack = "core" if name == CORE else rel(p["dir"] / "pack.yaml")
    skills, principles, roles = all_skills(), all_principles(), all_roles()

    if name != CORE:
        errors += schema_errors(man, "pack", where_pack)
        req = (man.get("requires") or {}).get("core")
        if req and not version_matches(config()["version"], req):
            errors.append(f"{where_pack}: requires core {req}, but this is core {config()['version']}")
        for dep, spec in depends_on(name).items():
            if dep not in packs():
                errors.append(f"{where_pack}: depends on '{dep}', which is not installed")
            elif not version_matches(packs()[dep]["manifest"]["version"], spec):
                errors.append(f"{where_pack}: depends on {dep}@{spec}, installed is {packs()[dep]['manifest']['version']}")
        if man.get("cos") and not (p["dir"] / man["cos"]).exists():
            errors.append(f"{where_pack}: cos file {man['cos']} missing")
        if man.get("cos_section") and not (p["dir"] / man["cos_section"]).exists():
            errors.append(f"{where_pack}: cos_section file {man['cos_section']} missing")
        for kind, handler in (man.get("actions") or {}).items():
            script = (shlex.split(handler) or [""])[0]
            if not script or not (p["dir"] / script).is_file():
                errors.append(f"{where_pack}: actions '{kind}': handler script '{script}' not found in the pack")
        installed_version = (p.get("entry") or {}).get("version")
        if check_grants and installed_version and installed_version != man.get("version"):
            warnings.append(f"{where_pack}: version is {man.get('version')} but packs.yaml recorded "
                            f"{installed_version}; run `pmos pack add {rel(p['dir'])} --upgrade`")

    # skills and principles
    for sid, path in skills.items():
        if not sid.startswith(f"{name}:"):
            continue
        meta, _ = frontmatter(path)
        expected = render_name(sid)
        if "name" in meta and meta["name"] != expected:  # optional; `render` writes it
            errors.append(f"{rel(path)}: frontmatter name should be '{expected}' or left out (got {meta.get('name')!r})")
        if not meta.get("description"):
            errors.append(f"{rel(path)}: missing description")
    for pid, pr in principles.items():
        if pr["pack"] != name:
            continue
        if pr["meta"].get("kind") != "principle":
            errors.append(f"{rel(pr['path'])}: principles need 'kind: principle'")
        if not pr["meta"].get("check"):
            errors.append(f"{rel(pr['path'])}: principles need a one-line 'check' the Reviewer can score")
        if pr["meta"].get("always") and name != CORE:
            errors.append(f"{rel(pr['path'])}: only core principles may set 'always: true'")

    # document standards (standards/<name>.yaml) and product overlays
    if name != CORE:
        errors += standard_file_errors(p["dir"])
        for product, refs in (man.get("overlays") or {}).items():
            for s in refs or []:
                errors += skill_ref_errors(f"{where_pack}: overlays.{product}", s, name)

    # roles
    if paths["roles"] and paths["roles"].exists():
        errors += schema_errors(load_yaml(paths["roles"]), "roles", rel(paths["roles"]))
    agents = all_agents()
    context_dir = ROOT / config()["paths"]["context"]
    for fq, r in roles.items():
        if r["_pack"] != name:
            continue
        if r.get("agent") not in agents:
            errors.append(f"role {fq}: agent '{r.get('agent')}' not found")
        for s in r.get("skills", []):
            errors += skill_ref_errors(f"role {fq}", s, name)
        for pr in r.get("principles", []):
            pid = q_skill(pr, name)
            if pid not in principles:
                errors.append(f"role {fq}: principle '{pid}' not found")
            else:
                err = visibility_error(name, pid.split(":")[0], "principles", pid.split(":", 1)[1])
                if err:
                    errors.append(f"role {fq}: {err}")
        for c in r.get("context", []):
            if not (context_dir / c).exists():
                warnings.append(f"role {fq}: context file '{c}' not found in context/")

    # agents
    for aname, (meta, _b, path, apack) in agents.items():
        if apack != name:
            continue
        errors += schema_errors(meta, "agent", f"{rel(path)} frontmatter")

    # modes
    mode_names = set()
    for m in [m for m in discover_modes() if m["pack"] == name]:
        mm, where = m["manifest"], rel(m["path"])
        errs = schema_errors(mm, "mode", where)
        type_errs = type_vocab_errors(mm, where)
        if type_errs:  # say it once, in words, instead of the schema's pattern message
            errs = [e for e in errs if not re.match(rf"{re.escape(where)}: (accepts|returns)/", e)] + type_errs
        if errs:
            errors += errs
            continue
        mode_names.add(mm["name"])
        if mm["name"].split("/")[0] != name:
            errors.append(f"{where}: mode name must start with '{name}/' (got {mm['name']})")
        skill_path = m["dir"] / mm.get("skill", "SKILL.md")
        if not skill_path.exists():
            errors.append(f"{where}: skill file {rel(skill_path)} missing")
        else:
            meta, _ = frontmatter(skill_path)
            if "name" in meta and meta["name"] != render_name(mm["name"]):  # optional; `render` writes it
                errors.append(f"{rel(skill_path)}: frontmatter name should be '{render_name(mm['name'])}' or left out")
            if not meta.get("description"):
                errors.append(f"{rel(skill_path)}: missing description")
        for rref in [mm["default_role"], *mm.get("roles", [])]:
            try:
                resolve_role(rref, name)
            except PmosError as e:
                errors.append(f"{where}: {e}")
        for pr in mm.get("principles", []):
            pid = q_skill(pr, name)
            if pid not in principles:
                errors.append(f"{where}: principle '{pid}' not found")
            else:
                err = visibility_error(name, pid.split(":")[0], "principles", pid.split(":", 1)[1])
                if err:
                    errors.append(f"{where}: {err}")
        for s in mm.get("skills", []) or []:
            errors += skill_ref_errors(where, s, name)
        errors += mode_standard_errors(mm, where, name)
        errors += principle_once_errors(mm, where, name)
        errors += done_errors(mm, where, name)
        for call in mm.get("calls", []):
            if call == "*":     # any mode visible to this pack; checked when a child is created
                continue
            try:
                resolve_mode(call, from_pack=name)
            except PmosError as e:
                errors.append(f"{where}: calls '{call}': {e}")
        evals_dir = m["dir"] / mm.get("evals", "evals/")
        if not list(evals_dir.glob("*.json")):
            errors.append(f"{where}: no golden tasks in {rel(evals_dir)} (no evals, no registration)")
        if check_grants and grant_excess(m):
            errors.append(f"{where}: {grant_excess_message(m)}")

    # exports must exist
    if name != CORE:
        exports = man.get("exports") or {}
        exported = [q_role(n, name) for n in exports.get("modes", []) or []]
        for mname in exported:
            if mname not in mode_names:
                errors.append(f"{where_pack}: exports mode '{mname}', which the pack doesn't contain")
        for rname in exports.get("roles", []) or []:
            if f"{name}/{rname}" not in roles:
                errors.append(f"{where_pack}: exports role '{rname}', which the pack doesn't define")
        for sname in exports.get("skills", []) or []:
            if f"{name}:{sname}" not in skills:
                errors.append(f"{where_pack}: exports skill '{sname}', which the pack doesn't contain")
        for pname in exports.get("principles", []) or []:
            if f"{name}:{pname}" not in principles:
                errors.append(f"{where_pack}: exports principle '{pname}', which the pack doesn't contain")
        for sname in exports.get("standards", []) or []:
            if q_standard(sname, name) not in all_standards():
                errors.append(f"{where_pack}: exports standard '{sname}', which the pack doesn't contain "
                              f"(standards/{sname.split('/')[-1]}.yaml)")
        router = man.get("router")
        if router and q_role(router, name) not in exported:
            errors.append(f"{where_pack}: router '{router}' must be an exported mode")
        called, star = set(), False
        for m in [m for m in discover_modes() if m["pack"] == name]:
            for call in m["manifest"].get("calls", []) or []:
                star = star or call == "*"
                called.add(split_ref(call)[0])
        if not star:
            for mname in sorted(mode_names - set(exported) - called):
                warnings.append(f"mode {mname} is internal (not in exports.modes) and no mode of pack '{name}' "
                                f"calls it, so nothing can start it; export it or add it to a mode's calls")
    if name != CORE:
        errors += channel_errors(name)
    errors += eval_errors(name)      # eval@1: every case valid, every feature covered
    rep = lint_report([name])        # tightness: budgets, mode structure, filler, cite don't copy
    errors += [f"lint: {e}" for e in rep["error_lines"]]
    warnings += [f"lint: {w}" for w in rep["warning_lines"]]
    return errors, warnings


# --------------------------------------------------------------------------- lint (tightness)
def tightness_module():
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import tightness
    return tightness


def components_of(name: str, d: Path, man: dict) -> list[dict]:
    """The text a pack ships for agents to load, as tightness components (see scripts/tightness.py)."""
    core, out = name == CORE, []
    skills = ROOT / config()["paths"]["skills"] if core else d / "skills"
    for f in sorted(skills.rglob("SKILL.md")) if skills.is_dir() else []:
        local = f.parent.relative_to(skills).as_posix()
        principle = local.startswith("principles/") and local.count("/") == 1
        out.append({"file": rel(f), "kind": "principle" if principle else "skill", "pack": name,
                    "id": f"{name}:{local.split('/', 1)[1] if principle else local}", "text": f.read_text(encoding="utf-8")})
    agents = ROOT / config()["paths"]["agents"] if core else d / "agents"
    for f in sorted(agents.glob("*.md")) if agents.is_dir() else []:
        out.append({"file": rel(f), "kind": "agent", "pack": name, "text": f.read_text(encoding="utf-8")})
    for mf in [] if core else sorted((d / "modes").glob("*/mode.yaml")):
        mm = load_yaml(mf) or {}
        sf = mf.parent / str(mm.get("skill") or "SKILL.md")
        if sf.exists():
            out.append({"file": rel(sf), "kind": "mode", "pack": name, "id": mm.get("name"),
                        "text": sf.read_text(encoding="utf-8")})
        lines = [ln["text"] for ln in done_lines(mm, name)
                 if ln["kind"] != "code" and not ln.get("principle") and ln.get("source") != "standard"]
        if lines:
            out.append({"file": rel(mf), "kind": "manifest", "pack": name, "id": mm.get("name"), "text": lines})
    for sf in [] if core else sorted((d / "standards").glob("*.yaml")):
        try:
            data = load_yaml(sf) or {}
        except yaml.YAMLError:
            continue                     # validate reports it
        labels, lines = [], []
        for s in data.get("sections") or [] if isinstance(data, dict) else []:
            if isinstance(s, dict) and s.get("contains"):
                labels.append(f"sections.{s.get('id')}.contains")
                lines.append(str(s["contains"]))
        for i, j in enumerate((data.get("judgment") or []) if isinstance(data, dict) else [], 1):
            labels.append(f"judgment.{i}")
            lines.append(str(j))
        out.append({"file": rel(sf), "kind": "standard", "pack": name, "id": f"{name}:standards/{sf.stem}",
                    "text": lines, "labels": labels})
    for key in [] if core else ("cos", "cos_section"):
        if man.get(key) and (d / man[key]).is_file():
            out.append({"file": rel(d / man[key]), "kind": "cos", "pack": name,
                        "text": (d / man[key]).read_text(encoding="utf-8")})
    roles = ROOT / config()["paths"]["roles"] if core else d / "roles.yaml"
    if roles.is_file():
        for rname, r in ((load_yaml(roles) or {}).get("roles") or {}).items():
            out.append({"file": rel(roles), "kind": "role", "pack": name, "id": f"{name}/{rname}",
                        "text": [str(r.get("persona") or ""), *[str(x) for x in r.get("rubric") or []]]})
    return out


def lint_report(names: list[str] | None = None, override: tuple[str, Path, dict] | None = None) -> dict:
    """The tightness lint over NAMES (installed packs, core included; default: all), with every installed
    pack as context. OVERRIDE = (name, dir, manifest): a pack folder that replaces (or joins) the
    installed packs, e.g. a staged copy; NAMES then defaults to it."""
    view = {n: (p["dir"], p["manifest"]) for n, p in packs().items()}
    if override:
        view[override[0]] = (override[1], override[2])
        names = names or [override[0]]
    comps = {n: components_of(n, d, m) for n, (d, m) in view.items()}
    cos, cos_files = config().get("cos_pack"), []
    if cos in view and view[cos][1].get("cos"):
        cos_files.append(rel(view[cos][0] / view[cos][1]["cos"]))
    cos_files += [rel(d / m["cos_section"]) for n, (d, m) in view.items() if n != CORE and m.get("cos_section")]
    targets = [c for n in (names or list(view)) for c in comps.get(n, [])]
    return tightness_module().lint(targets, [c for cs in comps.values() for c in cs], config(), cos_files)


def cmd_lint(args) -> int:
    reports = []
    names = [t for t in args.targets if not (Path(t) / "pack.yaml").exists()]
    for t in names:
        if t not in packs():
            raise PmosError(f"'{t}' is not core, an installed pack or a pack folder")
    if names or not args.targets:
        reports.append(lint_report(names or None))
    for t in [t for t in args.targets if (Path(t) / "pack.yaml").exists()]:
        d = Path(t).resolve()
        man = load_yaml(d / "pack.yaml") or {}
        if not man.get("name"):
            raise PmosError(f"{t}/pack.yaml has no name")
        reports.append(lint_report(override=(man["name"], d, man)))
    report = reports[0] if len(reports) == 1 else {
        "contract": "lint@1", "files": [f for r in reports for f in r["files"]],
        "manual": next((r["manual"] for r in reports if r["manual"]), None),
        "errors": sum(r["errors"] for r in reports), "warnings": sum(r["warnings"] for r in reports),
        "error_lines": [e for r in reports for e in r["error_lines"]],
        "warning_lines": [w for r in reports for w in r["warning_lines"]], "notes": [n for r in reports for n in r["notes"]]}
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(tightness_module().table(report) + "\n")
        for kind, lines in (("error", report["error_lines"]), ("warn", report["warning_lines"]), ("note", report["notes"])):
            for line in lines:
                print(f"{kind}: {line}")
        print(f"lint: {len(report['files'])} file(s), {report['errors']} error(s), {report['warnings']} warning(s)")
    return 1 if report["errors"] else 0


def validate_all() -> tuple[list[str], list[str]]:
    errors, warnings = [], []
    for name in packs():
        e, w = check_pack(name)
        errors += e
        warnings += w
    names = {}
    for sid in all_skills():
        names.setdefault(render_name(sid), []).append(sid)
    for m in discover_modes():
        names.setdefault(render_name(m["manifest"].get("name", "")), []).append(m["manifest"].get("name"))
    for rn, refs in names.items():
        if len(refs) > 1:
            errors.append(f"rendered skill name '{rn}' is used by {refs}")
    errors += grant_record_errors()
    warnings += missing_pack_references()
    cos = config().get("cos_pack")
    if cos not in packs():
        errors.append(f"pm-os.yaml: cos_pack '{cos}' is not installed")
    elif not packs()[cos]["manifest"].get("cos"):
        errors.append(f"pm-os.yaml: cos_pack '{cos}' doesn't supply a Chief of Staff (no 'cos' in pack.yaml)")
    else:
        errors += placeholder_errors()
        agents_md = ROOT / "AGENTS.md"
        if not agents_md.exists() or agents_md.read_text(encoding="utf-8") != build_agents_md():
            warnings.append("AGENTS.md is out of date; run `pmos catalog` (or `pmos render agents-md`)")
    # a cross-file lint finding is reported by each pack it touches; say it once
    return list(dict.fromkeys(errors)), list(dict.fromkeys(warnings))


def grant_approvals_file() -> Path:
    """Append-only record of every grant approval `pack add` wrote; packs.yaml must agree with it."""
    return ROOT / config()["paths"]["state"] / "grant-approvals.jsonl"


def record_grant_approval(name: str, version: str, grants: dict) -> None:
    f = grant_approvals_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    with open(f, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"ts": now(), "pack": name, "version": version, "grants": grants}) + "\n")


def recorded_grants() -> dict[str, dict]:
    """pack -> the last approval recorded for it."""
    out = {}
    f = grant_approvals_file()
    if f.exists():
        for line in f.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rec = json.loads(line)
                out[rec["pack"]] = rec
    return out


def grant_record_errors() -> list[str]:
    errors, recorded = [], recorded_grants()
    for e in install_list():
        approved, rec = e.get("grants_approved") or {}, recorded.get(e["name"])
        fix = f"re-approve with `pmos pack add {e['path']} --upgrade --approve-grants`"
        if rec is None:
            errors.append(f"packs.yaml: pack '{e['name']}' has grants_approved but no recorded grant approval in "
                          f"{rel(grant_approvals_file())}; {fix}")
        elif rec["grants"] != approved:
            errors.append(f"packs.yaml: pack '{e['name']}' grants_approved {approved} differs from the grant "
                          f"approval recorded in {rel(grant_approvals_file())} {rec['grants']} (edited by hand?); "
                          f"{fix}")
    return errors


def pack_texts(name: str) -> list[Path]:
    """The Markdown an installed pack ships (SKILL.md files, COS manual and sections, agents)."""
    p = packs()[name]
    if name == CORE:
        paths = pack_paths(p)
        return sorted([*paths["agents"].glob("*.md"), *paths["skills"].rglob("*.md")])
    return sorted(p["dir"].rglob("*.md"))


def missing_pack_references() -> list[str]:
    """Text in installed packs that names a mode (<pack>/<mode>) or path (packs/<pack>/) of a pack that
    isn't installed, e.g. after `pmos pack remove`. Known packs: those on disk beside the installed ones,
    and those with a recorded grant approval."""
    installed = set(packs())
    absent: dict[str, set[str]] = {n: set() for n in recorded_grants() if n not in installed}
    for root in {p["dir"].parent for n, p in packs().items() if n != CORE}:
        for man_path in root.glob("*/pack.yaml"):
            name = (load_yaml(man_path) or {}).get("name")
            if name and name not in installed:
                absent[name] = {(load_yaml(m) or {}).get("name", "") for m in man_path.parent.glob("modes/*/mode.yaml")}
    if not absent:
        return []
    names = "|".join(re.escape(n) for n in sorted(absent))
    pats = [(re.compile(rf"(?<![\w/.-])packs/({names})/"), lambda m: True),
            (re.compile(rf"(?<![\w/.-])({names})/[a-z0-9-]+"), lambda m: m.group(0) in absent[m.group(1)])]
    out = []
    for name in sorted(installed):
        for path in pack_texts(name):
            for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                for pat, hit in pats:
                    for m in pat.finditer(line):
                        if hit(m):
                            out.append(f"{rel(path)}:{i}: names {m.group(0)}, but pack '{m.group(1)}' is not "
                                       f"installed")
    return out


def cmd_validate(_args) -> int:
    errors, warnings = validate_all()
    for w in warnings:
        print(f"warn: {w}")
    for e in errors:
        print(f"error: {e}")
    if errors:
        print(f"\n{len(errors)} error(s).")
        return 1
    non_core = [n for n in packs() if n != CORE]
    print(f"OK: {len(non_core)} pack(s) ({', '.join(non_core)}), {len(discover_modes())} mode(s), "
          f"{len(all_roles())} role(s), {len(all_skills()) - len(all_principles())} skill(s), "
          f"{len(all_principles())} principle(s), {len(all_standards())} standard(s), {len(all_agents())} agent(s).")
    return 0


# --------------------------------------------------------------------------- packs CLI
def mode_grants(pack: str) -> dict[str, str]:
    """What a pack asks for: its modes' grants, and its own pack-level grants (channels that send)."""
    union: dict[str, str] = {}
    pack_level = ((packs().get(pack) or {}).get("manifest") or {}).get("grants") or {}
    sources = [pack_level] + [m["manifest"].get("grants") or {} for m in discover_modes() if m["pack"] == pack]
    for grants in sources:
        for system, level in grants.items():
            if GRANT_LEVEL.get(level, 0) > GRANT_LEVEL.get(union.get(system), 0):
                union[system] = level
    return dict(sorted(union.items()))


def cmd_pack_list(_args) -> int:
    entries = install_list()
    if not entries:
        print("(no packs installed)")
    for e in entries:
        p = packs().get(e["name"])
        summary = p["manifest"].get("summary", "") if p else "(missing)"
        grants = ", ".join(f"{k}:{v}" for k, v in (e.get("grants_approved") or {}).items()) or "none"
        flag = "" if e.get("enabled", True) else " (disabled)"
        print(f"{e['name']:<10} {e.get('version', ''):<8} {e.get('source', ''):<12} grants: {grants}{flag}\n"
              f"{'':<10} {summary}")
    return 0


def cmd_pack_add(args) -> int:
    d = Path(args.path).resolve()
    man_path = d / "pack.yaml"
    if not man_path.exists():
        raise PmosError(f"no pack.yaml in {args.path}")
    man = load_yaml(man_path) or {}
    validate_against(man, "pack", rel(man_path))
    name = man["name"]
    entries = install_list()
    existing = next((e for e in entries if e["name"] == name), None)
    if existing and not args.upgrade:
        raise PmosError(f"pack '{name}' is already installed ({existing.get('version')}); use --upgrade")
    if existing and version_tuple(man["version"]) <= version_tuple(str(existing.get("version", "0"))):
        raise PmosError(f"pack '{name}' {man['version']} is not newer than the installed {existing.get('version')}: "
                        f"an upgrade must raise the pack's version (bump `version` in {rel(man_path)})")

    stored_path = rel(d) if str(d).startswith(str(ROOT)) else str(d)
    entry = {"name": name, "version": man["version"], "path": stored_path, "source": args.source,
             "enabled": True, "grants_approved": {}, "installed_at": now()}
    trial = [e for e in entries if e["name"] != name] + [entry]
    _CACHE.clear()
    _CACHE["install"] = trial
    errors, warnings = check_pack(name, check_grants=False)
    for w in warnings:
        print(f"warn: {w}")
    if errors:
        clear_cache()
        print(f"Admission failed for pack '{name}':")
        for e in errors:
            print(f"  - {e}")
        return 1
    if existing:  # an upgrade must not silently break the packs that depend on this one
        broken = {}
        for dep in [n for n in packs() if n not in (CORE, name) and name in depends_on(n)]:
            dep_errors, _ = check_pack(dep, check_grants=False)
            if dep_errors:
                broken[dep] = dep_errors
        if broken:
            print(f"{'warn' if args.force else 'Upgrade refused'}: upgrading '{name}' to {man['version']} breaks "
                  f"pack(s) that depend on it: {', '.join(broken)}")
            for dep, errs in broken.items():
                for e in errs:
                    print(f"  - {dep}: {e}")
            if not args.force:
                clear_cache()
                print("Upgrade those packs first, or re-run with --force to install anyway.")
                return 1

    if args.with_golden and not (config().get("eval") or {}).get("command"):
        clear_cache()
        raise PmosError("--with-golden runs the golden cases through eval.command; set eval.command in pm-os.yaml")
    if not os.environ.get("PMOS_EVAL_SANDBOX"):     # (inside the sandbox itself: just install)
        failures = admission_evals(name, d, man, args.with_golden)
        if failures:
            clear_cache()
            print(f"Admission failed for pack '{name}': its evals failed in the sandbox:")
            for f in failures:
                print(f"  - {f}")
            return 1

    requested = mode_grants(name)
    previously = (existing or {}).get("grants_approved") or {}
    widened = {k: v for k, v in requested.items() if GRANT_LEVEL.get(v, 0) > GRANT_LEVEL.get(previously.get(k), 0)}
    if args.dry_run:
        clear_cache()
        print(f"Dry run: pack '{name}' {man['version']} passes admission. Grants it would hold:")
        for k, v in requested.items():
            print(f"  - {k}: {v}" + ("  (new or wider; needs --approve-grants)" if k in widened else ""))
        if not requested:
            print("  (none)")
        return 0
    if widened and not args.approve_grants:
        clear_cache()
        print(f"Pack '{name}' {man['version']} passed admission and requests these grants:")
        for k, v in requested.items():
            print(f"  - {k}: {v}" + ("  (new)" if k in widened else ""))
        print("Writes are always executed by the Operator after approval; these grants define what the pack's "
              "modes may read or propose.\nRe-run with --approve-grants to install.")
        return 1
    entry["grants_approved"] = requested
    save_install_list(trial)
    record_grant_approval(name, man["version"], requested)
    write_catalog()
    print(f"{'upgraded' if existing else 'installed'} {name} {man['version']} from {stored_path} "
          f"({len([m for m in discover_modes() if m['pack'] == name])} mode(s)); catalog and AGENTS.md updated")
    return 0


def cmd_pack_path(args) -> int:
    if args.name not in packs() or args.name == CORE:
        raise PmosError(f"pack '{args.name}' is not installed")
    print(packs()[args.name]["dir"])
    return 0


def cmd_path(args) -> int:
    keys = sorted(config()["paths"])
    if args.name not in keys:
        raise PmosError(f"unknown path '{args.name}'; paths in pm-os.yaml: {', '.join(keys)}")
    print(path_of(args.name) if args.name in ("state", "traces", "outputs") else ROOT / config()["paths"][args.name])
    return 0


def cmd_pack_remove(args) -> int:
    entries = install_list()
    if not any(e["name"] == args.name for e in entries):
        raise PmosError(f"pack '{args.name}' is not installed")
    if args.name == config().get("cos_pack"):
        raise PmosError(f"'{args.name}' supplies the Chief of Staff; set cos_pack in pm-os.yaml to another pack first")
    dependents = [n for n in packs() if n not in (CORE, args.name) and args.name in depends_on(n)]
    if dependents:
        raise PmosError(f"can't remove '{args.name}': {', '.join(dependents)} depend(s) on it")
    open_tasks = [t["envelope"]["id"] for t in all_tasks()
                  if t.get("pack") == args.name and t["state"] not in TERMINAL]
    if open_tasks:
        raise PmosError(f"can't remove '{args.name}' while it has open tasks: {', '.join(open_tasks)}")
    save_install_list([e for e in entries if e["name"] != args.name])
    write_catalog()
    print(f"removed {args.name}; catalog and AGENTS.md updated")
    return 0


# --------------------------------------------------------------------------- catalog & AGENTS.md
def exported_modes(pack: str) -> list[dict]:
    return [m for m in discover_modes() if m["pack"] == pack and is_exported(pack, "modes", m["manifest"]["name"])]


def packs_table() -> list[str]:
    lines = ["| Pack | Version | What it covers | Router | Modes | Source |",
             "| --- | --- | --- | --- | --- | --- |"]
    for name, p in packs().items():
        if name == CORE:
            continue
        man = p["manifest"]
        modes = ", ".join(f"`{m['manifest']['name']}`" for m in exported_modes(name)) or "—"
        lines.append(f"| `{name}` | {man['version']} | {man.get('summary', '')} | "
                     f"{('`' + man['router'] + '`') if man.get('router') else '—'} | {modes} | {p['source']} |")
    return lines


def mode_rows(pack: str, include_internal: bool) -> list[str]:
    lines = ["| Mode | Version | Verbs | What it does | Accepts | Approval |",
             "| --- | --- | --- | --- | --- | --- |"]
    for m in sorted(discover_modes(), key=lambda m: m["manifest"]["name"]):
        if m["pack"] != pack:
            continue
        mm = m["manifest"]
        internal = not is_exported(pack, "modes", mm["name"])
        if internal and not include_internal:
            continue
        accepts = ", ".join(f"{k}: {v}" for k, v in mm.get("accepts", {}).items())
        lines.append(f"| `{mm['name']}`{' (internal)' if internal else ''} | {mm['version']} | "
                     f"{', '.join(mm.get('verbs', []))} | {mm.get('summary', '')} | {accepts} | {mm.get('approval')} |")
    return lines


PLACEHOLDER = re.compile(r"\{\{\s*([A-Za-z_][\w.-]*)\s*\}\}")   # {{cos.inline_max_tool_calls}} in COS.md


def setting(dotted: str):
    """A pm-os.yaml value by dotted path, or KeyError."""
    cur = config()
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            raise KeyError(dotted)
        cur = cur[part]
    return cur


def fill_placeholders(text: str) -> str:
    """{{dotted.key}} -> its pm-os.yaml value, so the CoS manual states the configured numbers; unknown
    keys stay as they are (validate reports them)."""
    def sub(m):
        try:
            return str(setting(m.group(1)))
        except KeyError:
            return m.group(0)
    return PLACEHOLDER.sub(sub, text)


def cos_manual_files() -> list[Path]:
    cos = packs()[config()["cos_pack"]]
    return [cos["dir"] / cos["manifest"]["cos"]] + [p["dir"] / p["manifest"]["cos_section"] for n, p in packs().items()
                                                   if n != CORE and p["manifest"].get("cos_section")]


def placeholder_errors() -> list[str]:
    out = []
    for f in cos_manual_files():
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            for m in PLACEHOLDER.finditer(line):
                try:
                    setting(m.group(1))
                except KeyError:
                    out.append(f"{rel(f)}:{i}: placeholder {{{{{m.group(1)}}}}} names no setting in pm-os.yaml")
    return out


def build_agents_md() -> str:
    cos = packs()[config()["cos_pack"]]
    # COS.md's frontmatter (its budget, budget_reason) is for lint; the manual is the body
    body = re.sub(r"\A---\s*\n.*?\n---\s*\n", "", (cos["dir"] / cos["manifest"]["cos"]).read_text(encoding="utf-8"), count=1, flags=re.S)
    manual = fill_placeholders(body.rstrip())
    sections = "".join("\n\n" + fill_placeholders((p["dir"] / p["manifest"]["cos_section"]).read_text(encoding="utf-8").strip())
                       for n, p in packs().items() if n != CORE and p["manifest"].get("cos_section"))
    return ("<!-- Generated by `pmos` from " + rel(cos["dir"] / cos["manifest"]["cos"]) +
            ", each installed pack's cos_section and packs.yaml. Edit those, then run `pmos catalog`. -->\n\n" +
            manual + sections +
            "\n\n## Installed packs\n\n" + "\n".join(packs_table()) +
            "\n\nUse `python scripts/pmos.py catalog --pack <pack>` for a pack's modes and what each accepts.\n")


def write_catalog() -> None:
    clear_cache()
    state = path_of("state")
    rows = []
    for m in discover_modes():
        mm = m["manifest"]
        rows.append({"name": mm["name"], "version": mm.get("version"), "pack": m["pack"],
                     "exported": is_exported(m["pack"], "modes", mm["name"]), "summary": mm.get("summary", ""),
                     "accepts": mm.get("accepts", {}), "verbs": mm.get("verbs", []),
                     "approval": mm.get("approval"), "source": m["source"]})
    write_json(state / "catalog.json", sorted(rows, key=lambda r: r["name"]))
    lines = ["# Catalog", "", f"Generated by `pmos catalog` at {now()}. The CoS routes from this.", "",
             "## Packs", "", *packs_table(), ""]
    for name in packs():
        if name == CORE or not exported_modes(name):
            continue
        lines += [f"## `{name}` modes", "", *mode_rows(name, include_internal=False), ""]
    state.mkdir(parents=True, exist_ok=True)
    (state / "catalog.md").write_text("\n".join(lines), encoding="utf-8")
    (ROOT / "AGENTS.md").write_text(build_agents_md(), encoding="utf-8")


def cmd_catalog(args) -> int:
    if args.pack:
        if args.pack not in packs() or args.pack == CORE:
            raise PmosError(f"pack '{args.pack}' is not installed")
        man = packs()[args.pack]["manifest"]
        print(f"# {args.pack} {man['version']} — {man.get('summary', '')}\n")
        if man.get("router"):
            print(f"Router (for goal-level asks): `{man['router']}`\n")
        print("\n".join(mode_rows(args.pack, include_internal=True)))
        return 0
    write_catalog()
    print(f"{len([n for n in packs() if n != CORE])} pack(s), {len(discover_modes())} mode(s) -> "
          f"{rel(path_of('state') / 'catalog.md')}; AGENTS.md regenerated")
    return 0


def cmd_role_show(args) -> int:
    if "/" not in args.role:
        raise PmosError("give a qualified role: <pack>/<role>, e.g. pm/doc-writer")
    role = all_roles().get(args.role)
    if not role:
        raise PmosError(f"role '{args.role}' not found")
    print("\n".join(role_lines(role)))
    return 0


def role_lines(role: dict, with_skills: bool = True) -> list[str]:
    owner, skills, principles = role["_pack"], all_skills(), all_principles()
    ctx = ROOT / config()["paths"]["context"]
    effort, _ = resolve_setting("effort", None, None, role)
    dispatch, _ = resolve_setting("dispatch", None, None, role)
    out = [f"## Role: {owner}/{role['_name']} (agent: {role['agent']}, tier: {role['tier']}, run: {dispatch}, "
           f"effort: {effort})",
           f"- persona: {role['persona']}"]
    for s in role.get("skills", []) if with_skills else []:
        sid = q_skill(s, owner)
        out.append(f"- skill: {rel(skills[sid]) if sid in skills else sid + ' (missing)'}")
    for pr in role.get("principles", []):
        pid = q_skill(pr, owner)
        if pid in principles:
            out.append(f"- principle {pid}: {principles[pid]['meta']['check']} ({rel(principles[pid]['path'])})")
    for c in role.get("context", []):
        out.append(f"- context: {rel(ctx / c)}")
    for r in role.get("rubric", []):
        out.append(f"- rubric: {r}")
    return out


# --------------------------------------------------------------------------- tasks
def tasks_dir() -> Path:
    return path_of("state") / "tasks"


def task_path(task_id: str) -> Path:
    return tasks_dir() / f"{task_id}.json"


def task_hash_path(task_id: str) -> Path:
    return tasks_dir() / f"{task_id}.sha256"


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_task(task_id: str) -> dict:
    p = task_path(task_id)
    if not p.exists():
        raise PmosError(f"no task {task_id}")
    hp = task_hash_path(task_id)
    if not hp.exists() or hp.read_text(encoding="utf-8").strip() != file_sha(p):
        raise PmosError(f"{rel(p)} was modified outside pmos (its hash doesn't match the one pmos recorded "
                        f"in {rel(hp)}). Task state changes only through `pmos task …`; restore the file or "
                        f"create a new task.")
    return load_json(p)


def save_task(task: dict) -> None:
    task["updated_at"] = now()
    p = task_path(task["envelope"]["id"])
    write_json(p, task)
    hp = task_hash_path(task["envelope"]["id"])
    hp.write_text(file_sha(p) + "\n", encoding="utf-8")


def all_tasks() -> list[dict]:
    d = tasks_dir()
    if not d.exists():
        return []
    return [load_json(p) for p in sorted(d.glob("T-*.json"))]


def next_task_id() -> str:
    """PMOS_TASK_SEQ_START sets the first sequence number (pmos eval gives each case its own range)."""
    day = dt.datetime.now().strftime("%Y%m%d")
    taken = [int(p.stem.split("-")[2]) for p in tasks_dir().glob(f"T-{day}-*.json")] if tasks_dir().exists() else []
    floor = int(os.environ.get("PMOS_TASK_SEQ_START") or 1)
    return f"T-{day}-{max(max(taken) + 1 if taken else 1, floor):03d}"


def trace(task: dict, event: str, **fields) -> None:
    traces = path_of("traces")
    traces.mkdir(parents=True, exist_ok=True)
    env = task["envelope"]
    record = {
        "ts": now(), "event": event, "task_id": env["id"], "mode": env["mode"], "pack": task.get("pack"),
        "mode_version": task.get("mode_version"), "role": task.get("role"),
        "parent": env.get("parent"), "origin": env.get("origin"), "effort": task.get("effort"), **fields,
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
REF_TYPES = ("doc_ref", "diff_ref")


def is_ref(v) -> bool:
    """A doc_ref / diff_ref value: a `scheme:` ref (jira:, doc:, url: …) or a path that exists."""
    return isinstance(v, str) and bool(v) and (bool(re.match(r"^[a-z]+:", v)) or (ROOT / v).exists())


for _t in REF_TYPES:
    TYPE_CHECKS[_t] = is_ref
TYPE_RE = re.compile(r"^(" + "|".join(TYPE_CHECKS) + r")\??$")


def type_problem(name: str, base: str, value, what: str = "input") -> str | None:
    """A message when VALUE doesn't fit type BASE, else None."""
    if TYPE_CHECKS[base](value):
        return None
    hint = " (an existing path or a scheme: ref)" if base in REF_TYPES else ""
    return f"{what} '{name}' should be {base}{hint}, got {json.dumps(value, ensure_ascii=False)[:80]}"


def type_vocab_errors(manifest: dict, where: str) -> list[str]:
    """accepts/returns types must come from the closed vocabulary (contracts/mode.schema.json)."""
    out = []
    for section in ("accepts", "returns"):
        for field, typ in (manifest.get(section) or {}).items():
            if not isinstance(typ, str) or not TYPE_RE.match(typ):
                out.append(f"{where}: {section}.{field}: unknown type {typ!r}; types are "
                           f"{', '.join(TYPE_CHECKS)}, optionally ending in '?'")
    return out


def is_from_ref(v) -> bool:
    return isinstance(v, dict) and "$from" in v


def check_inputs(inputs: dict, accepts: dict, mode_name: str) -> None:
    problems = []
    for field, typ in accepts.items():
        optional = str(typ).endswith("?")
        base = str(typ).rstrip("?")
        if field not in inputs:
            if not optional:
                problems.append(f"missing required input '{field}' ({base})")
            continue
        if is_from_ref(inputs[field]):  # checked by check_from_refs, resolved at `task move … running`
            continue
        problem = type_problem(field, base, inputs[field]) if base in TYPE_CHECKS else None
        if problem:
            problems.append(problem)
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
    if to == "failed":
        fail_dependents(task["envelope"]["id"])
    if to in TERMINAL and task["envelope"].get("parent"):
        maybe_wake_parent(task["envelope"]["parent"])


def fail_dependents(task_id: str) -> None:
    """A failed task can never be `done`, so its queued or blocked dependents can never start: fail them
    too (recursively, through transition), and let their parents wake as usual."""
    for t in all_tasks():
        if t["state"] in ("queued", "blocked") and task_id in (t["envelope"].get("depends_on") or []):
            transition(t, "failed", "pmos", f"dependency {task_id} failed")


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


def task_mode(task: dict) -> dict:
    """The mode a task was created with: its mode@version if still installed, otherwise the mode in the
    stored mode_dir (e.g. after the pack was upgraded under an in-flight task)."""
    try:
        return resolve_mode(f"{task['mode_name']}@{task['mode_version']}", check_visibility=False)
    except PmosError:
        d = ROOT / task["mode_dir"]
        if not (d / "mode.yaml").exists():
            raise PmosError(f"{task['envelope']['id']}: {task['mode_name']}@{task['mode_version']} is no longer "
                            f"installed and {task['mode_dir']}/mode.yaml is gone")
        return {"manifest": load_yaml(d / "mode.yaml") or {}, "dir": d, "path": d / "mode.yaml",
                "pack": task.get("pack"), "source": "stored mode_dir", "fallback": True}


def check_from_refs(inputs: dict, accepts: dict) -> list[str]:
    """Check every `{"$from": "<task id>", "output": "<name>"}` input; return the source task ids."""
    sources = []
    for field, v in inputs.items():
        if not is_from_ref(v):
            continue
        if set(v) != {"$from", "output"} or not all(isinstance(x, str) for x in v.values()):
            raise PmosError(f"input '{field}': a $from ref is {{\"$from\": \"<task id>\", \"output\": \"<name>\"}}")
        src = load_task(v["$from"])
        if src["state"] == "failed":
            raise PmosError(f"input '{field}': {v['$from']} failed, so its output '{v['output']}' will never exist")
        returns = {k: str(t).rstrip("?") for k, t in (task_mode(src)["manifest"].get("returns") or {}).items()}
        if v["output"] not in returns:
            raise PmosError(f"input '{field}': {v['$from']} ({src['mode_name']}) has no output '{v['output']}'; "
                            f"its returns: {', '.join(sorted(returns)) or 'none'}")
        want, have = str(accepts.get(field, "")).rstrip("?"), returns[v["output"]]
        if want and want != have and not (want == "string" and have in REF_TYPES):
            raise PmosError(f"input '{field}' is {want}, but {v['$from']}'s output '{v['output']}' is {have}")
        if v["$from"] not in sources:
            sources.append(v["$from"])
    return sources


def resolve_from_refs(task: dict) -> dict | None:
    """The task's inputs with each $from ref replaced by its source's result.outputs value (None if no refs)."""
    inputs = task["envelope"]["inputs"]
    if not any(is_from_ref(v) for v in inputs.values()):
        return None
    accepts = task_mode(task)["manifest"].get("accepts") or {}
    out = {}
    for field, v in inputs.items():
        if not is_from_ref(v):
            out[field] = v
            continue
        outputs = (load_task(v["$from"]).get("result") or {}).get("outputs") or {}
        if v["output"] in outputs:
            out[field] = outputs[v["output"]]
        elif not str(accepts.get(field, "")).endswith("?"):
            raise PmosError(f"input '{field}': {v['$from']}'s result has no output '{v['output']}'")
    return out


def check_outputs(result: dict, man: dict) -> None:
    """result.outputs against the mode's `returns`: names declared, required ones present, values typed."""
    returns = {k: str(t) for k, t in (man.get("returns") or {}).items()}
    outputs = result.get("outputs") or {}
    problems = []
    if result["status"] in ("done", "needs_approval"):
        missing = [k for k, t in returns.items() if not t.endswith("?") and k not in outputs]
        if missing:
            problems.append(f"result.outputs is missing {', '.join(missing)} (declared in {man['name']}'s returns)")
    unknown = sorted(set(outputs) - set(returns))
    if unknown:
        problems.append(f"result.outputs has unknown name(s) {', '.join(unknown)}; "
                        f"{man['name']} returns {', '.join(returns) or 'nothing'}")
    for k, v in outputs.items():
        base = returns.get(k, "").rstrip("?")
        problem = type_problem(k, base, v, what="output") if base in TYPE_CHECKS else None
        if problem:
            problems.append(problem)
    if problems:
        raise PmosError(f"outputs don't match {man['name']}'s returns:\n  - " + "\n  - ".join(problems))


def usd_spent(task: dict) -> float:
    if "usd_spent" in task:
        return float(task["usd_spent"])
    return float((((task.get("result") or {}).get("usage")) or {}).get("usd") or 0)


def tree_usd(task_id: str, override: dict) -> float:
    t = override.get(task_id) or load_task(task_id)
    return usd_spent(t) + sum(tree_usd(c, override) for c in t.get("children", []))


def check_tree_budget(task: dict, usd: float) -> None:
    """Children draw down their ancestors' budgets: refuse spending that takes any ancestor's tree
    (the ancestor plus all its descendants) over that ancestor's max_usd."""
    override = {task["envelope"]["id"]: {**task, "usd_spent": usd_spent(task) + usd}}
    pid = task["envelope"].get("parent")
    while pid:
        anc = load_task(pid)
        limit = (anc["envelope"].get("budget") or {}).get("max_usd")
        total = tree_usd(pid, override)
        if limit is not None and total > limit + 1e-9:
            raise PmosError(f"budget: this result's ${usd:g} takes {pid}'s tree to ${total:g}, over its "
                            f"max_usd ${limit:g} (children draw down the parent's budget)")
        pid = anc["envelope"].get("parent")


def task_manifest(task: dict) -> dict:
    """The mode.yaml a task runs under: the installed mode@version, else the stored mode_dir."""
    return task_mode(task)["manifest"]


def resolve_call(parent: dict, ref: str) -> dict:
    """Resolve a child's mode through the parent mode's `calls`: the name must match an entry (or the
    entry "*"), the entry's version pin applies, and the parent pack's visibility rules still hold."""
    pman = task_manifest(parent)
    calls = pman.get("calls") or []
    name, spec = split_ref(ref)
    for entry in calls:
        ename, epin = split_ref(entry)
        if entry != "*" and ename != name:
            continue
        try:
            mode = resolve_mode(ref if entry == "*" else (f"{name}@{epin}" if epin else name),
                                from_pack=parent.get("pack"))
        except PmosError as e:
            raise PmosError(f"{pman.get('name')} calls '{entry}': {e}")
        if spec and not version_matches(mode["manifest"]["version"], spec):
            raise PmosError(f"{ref} doesn't match the version {pman.get('name')} calls ('{entry}' resolves to "
                            f"{mode['manifest']['version']})")
        return mode
    raise PmosError(f"{pman.get('name')} may only start the modes in its calls ({', '.join(calls) or 'none'}); "
                    f"'{name}' is not one of them")


def envelope_floor(args, man: dict, parent: dict | None) -> tuple[str, str, str | None]:
    """(approval, risk, approval_from). The mode's approval and risk are a floor; a child may lower its
    approval only when its parent's approval is at least the mode's (its actions roll up to that gate)."""
    mode_approval, mode_risk = man.get("approval", "none"), man.get("risk", "medium")
    approval, risk = args.approval or mode_approval, args.risk or mode_risk
    if RISK_LEVEL[risk] < RISK_LEVEL[mode_risk]:
        raise PmosError(f"--risk {risk} is lower than {man['name']}'s risk ({mode_risk}); a mode's risk is a floor")
    approval_from = None
    if APPROVAL_LEVEL[approval] < APPROVAL_LEVEL[mode_approval]:
        if parent and APPROVAL_LEVEL[parent["envelope"]["approval"]] >= APPROVAL_LEVEL[mode_approval]:
            approval_from = parent["envelope"]["id"]
        else:
            raise PmosError(f"--approval {approval} is weaker than {man['name']}'s approval ({mode_approval}). "
                            f"Only a child whose parent's approval is at least {mode_approval} may lower it.")
    return approval, risk, approval_from


def parse_origin(raw: str | None) -> dict | None:
    if not raw:
        return None
    pack, _, ref = raw.partition(":")
    if not pack or not ref:
        raise PmosError(f"--origin is PACK:REF, e.g. cos:td-12 (got '{raw}')")
    return {"pack": pack, "ref": ref}


def cmd_task_new(args) -> int:
    parent = load_task(args.parent) if args.parent else None
    if parent and parent["state"] != "running":
        raise PmosError(f"parent {args.parent} is {parent['state']}; children can only be created while their "
                        f"parent is running")
    if parent and args.instructions:
        raise PmosError("--instructions is only for top-level tasks (the PM's own words, passed on by the CoS); "
                        "a child inherits its parent's instructions")
    from_pack = parent.get("pack") if parent else None     # None = the CoS: exported modes only
    mode = resolve_call(parent, args.mode) if parent else resolve_mode(args.mode, from_pack=from_pack)
    man, pack = mode["manifest"], mode["pack"]
    if grant_excess(mode):
        raise PmosError(grant_excess_message(mode))
    inputs = parse_inputs(args.inputs)
    check_inputs(inputs, man.get("accepts", {}), man["name"])
    from_sources = check_from_refs(inputs, man.get("accepts", {}))
    if args.verb is None:  # optional when the mode declares exactly one verb
        if len(man.get("verbs") or []) != 1:
            raise PmosError(f"{man['name']} supports verbs {man.get('verbs')}; pass --verb")
        args.verb = man["verbs"][0]
    if man.get("verbs") and args.verb not in man["verbs"]:
        raise PmosError(f"{man['name']} supports verbs {man['verbs']}, not '{args.verb}'")
    role = resolve_role(args.role or man["default_role"], pack)
    role_fq = f"{role['_pack']}/{role['_name']}"
    approval, risk, approval_from = envelope_floor(args, man, parent)
    effort = resolve_effort(args.effort, man, role, risk)
    dispatch, dispatch_source = resolve_setting("dispatch", args.dispatch, man, role)
    product = resolve_product(args.product, parent, pack)   # product, product_source, overlay_skills

    depth = 0
    if parent:
        depth = parent["envelope"].get("depth", 0) + 1
        max_depth = config()["defaults"].get("max_call_depth", 3)
        if depth > max_depth:
            raise PmosError(f"call depth {depth} exceeds max_call_depth {max_depth}")
        chain, cur = {man["name"]}, parent
        while cur:
            ancestor = split_ref(cur["envelope"]["mode"])[0]
            if ancestor in chain:
                raise PmosError(f"cycle: {man['name']} is already an ancestor of this task")
            chain.add(ancestor)
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
        "role": role_fq,
        "inputs": inputs,
        "acceptance": list(args.acceptance or []),   # extra must lines for this task (task-1, …)
        "risk": risk,
        "approval": approval,
        "budget": budget,
        "depends_on": (args.depends_on or []) + [s for s in from_sources if s not in (args.depends_on or [])],
        "parent": args.parent,
        "depth": depth,
        "reply_to": args.reply_to,
        "created_at": now(),
    }
    if args.workflow:
        envelope["workflow"] = args.workflow
    instructions_from = None
    if args.instructions:
        envelope["instructions"] = args.instructions
    elif parent and parent["envelope"].get("instructions"):  # the PM's instructions flow down to children
        envelope["instructions"] = parent["envelope"]["instructions"]
        instructions_from = parent.get("instructions_from") or parent["envelope"]["id"]
    origin = parse_origin(args.origin)
    if origin:
        envelope["origin"] = origin
    validate_against(envelope, "task", "envelope")
    for dep in envelope["depends_on"]:
        load_task(dep)

    task = {
        "envelope": envelope,
        "state": "queued",
        "pack": pack,
        "mode_name": man["name"],
        "mode_version": man["version"],
        "mode_dir": rel(mode["dir"]),
        "role": role_fq,
        "children": [],
        "revisions": 0,          # failed reviews, counted against max_revisions
        "change_requests": 0,    # the PM's "change X" (awaiting_approval -> revise); not counted
        "approvals": [],
        "approval_from": approval_from,
        **effort,                # effort, effort_source, effort_base, effort_risk_adjust
        "review_effort": review_effort(risk),
        "dispatch": dispatch,
        "dispatch_source": dispatch_source,
        **product,
        "result": None,
        "result_path": None,
        "history": [{"ts": now(), "from": None, "to": "queued", "by": args.by, "note": args.note}],
    }
    if instructions_from:
        task["instructions_from"] = instructions_from
    save_task(task)
    trace(task, "created", by=args.by)
    if parent:
        parent["children"].append(envelope["id"])
        save_task(parent)
    write_board()
    print(envelope["id"])
    return 0


def deps_pending(task: dict) -> list[str]:
    return [d for d in task["envelope"].get("depends_on", []) if load_task(d)["state"] != "done"]


def delegate_target(role: dict) -> str:
    """The subagent to run a task under ROLE: `<agent>-<tier>` when the agent is rendered per tier."""
    agent = all_agents().get(role["agent"])
    tiers = (agent[0].get("tiers") or []) if agent else []
    return f"{role['agent']}-{role['tier']}" if role.get("tier") in tiers else role["agent"]


def code_status(entry: dict, rec: dict | None) -> dict:
    """A checklist code line with what pmos recorded when it ran it (settled once it ran and passed)."""
    if rec is None:
        return {**entry, "settled": False}
    return {**entry, "settled": bool(rec["pass"]), "pass": bool(rec["pass"]), "exit": rec.get("exit"),
            "output": tail(rec.get("output"), 500)}


def review_checklist(task: dict, mode: dict, role: dict) -> list[dict]:
    """The lines a review judges, each with a stable id and a kind (`task show --checklist`, `task review
    --verdicts`): core principles; then must lines (the mode's done.must, the task's --acceptance lines,
    the PM's instructions, the musts of children reviewed here); then the must code lines, settled by pmos
    at `task result`; then should lines (done.should, cited principles that aren't musts, role rubrics)."""
    env, man = task["envelope"], mode["manifest"]
    lines, seen = [], set()

    def add(entry: dict) -> None:
        if entry["id"] not in seen:
            lines.append(entry)
            seen.add(entry["id"])

    for group, pid, pr in principles_for(mode, role):
        if group == "core":
            add({"id": pid, "kind": "core", "group": "core", "text": pr["meta"]["check"]})

    def add_done(owner: dict, man_: dict, pack: str, group: str, prefix: str = "") -> None:
        recs = {r["id"]: r for r in owner.get("done_code") or []}
        for ln in done_lines(man_, pack):
            if ln.get("principle") in seen:      # a core principle cited again
                continue
            entry = {"id": prefix + ln["id"], "kind": ln["kind"], "group": group, "text": ln["text"]}
            if ln["kind"] == "code":
                entry = code_status({**entry, "command": ln["command"]}, recs.get(ln["id"]))
            add(entry)
            if ln.get("principle"):
                seen.add(ln["principle"])
        oenv = owner["envelope"]
        for i, a in enumerate(oenv.get("acceptance") or [], 1):
            add({"id": f"{prefix}task-{i}", "kind": "must", "group": "task" if not prefix else group, "text": a})

    add_done(task, man, mode["pack"], "mode")
    if env.get("instructions"):
        add({"id": "pm-instructions", "kind": "must", "group": "pm instructions",
             "text": "Follows the PM's instructions", "instructions": env["instructions"]})
    later = []                       # should lines of the children, after this task's own
    children = [load_task(c) for c in task.get("children", [])]
    for child in [c for c in children if c.get("reviewed_with") == env["id"]]:
        cid = child["envelope"]["id"]
        cmode = {"manifest": task_manifest(child), "pack": child["pack"]}
        crole = all_roles().get(child["role"], {"_pack": child["pack"], "principles": [], "rubric": []})
        add_done(child, cmode["manifest"], child["pack"], f"child {cid}", prefix=f"{cid}:")
        later += [{"id": pid, "kind": "should", "group": f"child {cid}", "text": f"{pr['meta']['check']} (child {cid})"}
                  for group, pid, pr in principles_for(cmode, crole) if group != "core"]
        later += [{"id": f"{cid}:role-rubric-{i}", "kind": "should", "group": f"child {cid}", "text": r}
                  for i, r in enumerate(crole.get("rubric") or [], 1)]
    for group, pid, pr in principles_for(mode, role):
        if group != "core":
            add({"id": pid, "kind": "should", "group": f"{group} principle", "text": pr["meta"]["check"]})
    for i, r in enumerate(role.get("rubric") or [], 1):
        add({"id": f"role-rubric-{i}", "kind": "should", "group": "role rubric", "text": r})
    for entry in later:
        add(entry)
    return sorted(lines, key=lambda c: CHECKLIST_ORDER[c["kind"]])   # stable: keeps the order within a kind


def checklist_line(c: dict, state: bool = True) -> str:
    """One checklist line as Markdown, for the review brief and (without the run state) the golden grader."""
    text = c["text"] + (f": \"{c['instructions']}\"" if c.get("instructions") else "")
    if c["kind"] == "expect":
        return f"`{c['id']}` [expect] {text}"
    if c["kind"] == "code" and state:
        state = (f"settled by pmos: passed (exit {c.get('exit')})" if c.get("settled")
                 else "not run yet" if "pass" not in c else f"FAILED (exit {c.get('exit')})")
        return f"`{c['id']}` [code] {text} — {state}"
    return f"`{c['id']}` [{c['kind']}] {text}"


def task_skills(task: dict, mode: dict, role: dict) -> list[tuple[str, str, Path | None]]:
    """(tag, qualified ref, SKILL.md) for every skill a task loads: the role's, then the mode's, then the
    product overlay's (stored at `task new`), each once."""
    skills, out, seen = all_skills(), [], set()
    sources = [("role", role.get("skills") or [], role["_pack"]),
               ("mode", mode["manifest"].get("skills") or [], mode["pack"]),
               (f"overlay: {task.get('product')}", task.get("overlay_skills") or [], mode["pack"])]
    for tag, refs, owner in sources:
        for ref in refs:
            sid = q_skill(ref, owner)
            if sid not in seen:
                seen.add(sid)
                out.append((tag, sid, skills.get(sid)))
    return out


def standard_outline(man: dict, pack: str) -> list[str]:
    """The `task show` section that prints a mode's document standard: one line per section (title,
    required or optional, what it contains, its rules), then the forbidden patterns."""
    std = mode_standard(man, pack)
    if not std or not std["data"]:
        return []
    data = std["data"]
    out = ["", f"## Document standard: {std['ref']} (outputs.{std['output']}; check_doc.py runs it at task result)",
           f"{data.get('summary', '')}. Write these sections, in this order:"]
    for s in data.get("sections") or []:
        rules = []
        if s.get("numbered"):
            p = s["numbered"]["prefix"]
            rules.append(f"numbered {p}1, {p}2, …" + (" with no gaps" if s["numbered"].get("contiguous", True) else ""))
        if s.get("fields"):
            rules.append(f"a table with columns {', '.join(s['fields'])}")
        if s.get("min_items"):
            rules.append(f"at least {s['min_items']} items")
        out.append(f"- {s['title']} ({'required' if s.get('required') else 'optional'}): {s.get('contains', '')}"
                   + "".join(f" · {r}" for r in rules))
    out += [f"- never: {r['message']}" for r in data.get("forbid") or []]
    return out


def cmd_task_show(args) -> int:
    task = load_task(args.id)
    if args.json:
        print(json.dumps(task, indent=2, ensure_ascii=False))
        return 0
    env = task["envelope"]
    mode = task_mode(task)
    man = mode["manifest"]
    role = all_roles()[task["role"]]
    if args.checklist:
        print(json.dumps(review_checklist(task, mode, role), indent=2, ensure_ascii=False))
        return 0
    # Stable parts first (mode, role, principles, definition of done), so the prompt prefix caches across
    # tasks; everything specific to this task (id, envelope, history, result) comes after. A revision brief
    # (the lines that failed, with their fix) comes before everything: it is what the Worker does next.
    out = []
    brief = task.get("revision_brief")
    if brief and task["state"] in ("revise", "running"):
        source = {"code": "pmos ran the code lines", "review": "the review", "pm": "the PM"}.get(brief.get("from"), "")
        out += [f"## Revise first: fix these {len(brief['lines'])} line(s) ({source}), then resubmit", "",
                *[f"- `{ln['id']}`: {ln['fix']}" for ln in brief["lines"]], ""]
    out += [
        f"# {task['mode_name']}@{task['mode_version']}",
        f"delegate to: {delegate_target(role)} · effort: {task.get('effort', '—')} · run: {task.get('dispatch', 'background')}",
        "",
        f"## Mode (pack: {task.get('pack')})",
        f"- skill: {rel(mode['dir'] / man.get('skill', 'SKILL.md'))}",
    ]
    if man.get("calls"):
        out.append(f"- may call: {', '.join(man['calls'])}")
    for extra in man.get("roles", []):
        out.append(f"- also uses role: {q_role(extra, mode['pack'])} (`pmos role show {q_role(extra, mode['pack'])}`)")
    out += standard_outline(man, mode["pack"])
    out += ["", *role_lines(role, with_skills=False)]
    out += ["", "## Skills (load each before you start)"]
    out += [f"- [{tag}] {sid} ({rel(path) if path else 'missing'})" for tag, sid, path in task_skills(task, mode, role)]
    out += ["", "## Principles (read each before you start; the Reviewer scores these checks)"]
    for group, pid, pr in principles_for(mode, role):
        out.append(f"- [{group}] {pid}: {pr['meta']['check']} ({rel(pr['path'])})")
    out += ["", "## Definition of done (mode.yaml `done` and its standard's lines: every must holds, code lines run "
                "at `task result`; the share of should lines that hold sets the score)"]
    out += [f"- {ln['kind']} `{ln['id']}`: {ln['text']}" for ln in done_lines(man, mode["pack"])]
    out += [
        "",
        f"# Task {env['id']} · {env['verb']} · state: {task['state']}",
        f"- approval: {env['approval']} · risk: {env['risk']} · review effort: {task.get('review_effort', '—')}",
        f"- outputs: {rel(path_of('outputs') / env['id'])}/",
        *([f"- product: {task['product']} (from {task.get('product_source')})"] if task.get("product") else []),
        "",
    ]
    if mode.get("fallback"):
        out += [f"Note: {task['mode_name']}@{task['mode_version']} is no longer installed; showing the mode from "
                f"its stored directory {task['mode_dir']} (now {man.get('name')}@{man.get('version')}).", ""]
    if env.get("instructions"):
        source = (f"inherited from parent task {task['instructions_from']}; " if task.get("instructions_from")
                  else "")
        out += [f"## Instructions from the PM ({source}follow these; they come from the PM directly)", "",
                *[f"> {line}" for line in env["instructions"].splitlines()], ""]
    task_musts = [f"- must `task-{i}`: {a}" for i, a in enumerate(env.get("acceptance") or [], 1)]
    if env.get("instructions"):
        task_musts.append("- must `pm-instructions`: Follows the PM's instructions (above)")
    if task_musts:
        out += ["## Also done for this task (must)", "", *task_musts, ""]
    if env.get("origin"):
        out += [f"Origin: {env['origin']['pack']}:{env['origin']['ref']}.", ""]
    if task.get("inputs_resolved") is not None:
        out += ["## Inputs resolved (use these: each `$from` ref replaced by its source's output)",
                "```json", json.dumps(task["inputs_resolved"], indent=2, ensure_ascii=False), "```", ""]
    elif any(is_from_ref(v) for v in env.get("inputs", {}).values()):
        out += ["Inputs with `$from` refs are resolved when the task moves to running.", ""]
    out += ["## Envelope", "```json", json.dumps(env, indent=2, ensure_ascii=False), "```"]
    pending = deps_pending(task)
    if pending:
        out += ["", f"**Waiting on dependencies:** {', '.join(pending)}"]
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
        merged = {m["idempotency_key"]: m["from"] for m in task.get("merged_actions", [])}
        sent_map = {x["key"]: x["receipt"] for x in task.get("sent") or []}
        ext = external_systems()
        unsent = pending_send(task) if task["state"] == "approved" else []
        if unsent:
            out.append(f"- pending send: {', '.join(a['idempotency_key'] for a in unsent)} "
                       f"(send each, then `pmos action run {env['id']} --receipt KEY=ID`)")
        for a in task["result"].get("actions", []):
            key = a["idempotency_key"]
            status = ""
            if a["system"] in ext and task["state"] in ("approved", "done"):
                status = f" · sent {sent_map[key]}" if key in sent_map else " · pending send"
            out.append(f"- action: {a['system']}.{a['op']} · {a.get('preview', key)}"
                       + (f" (from {merged[key]})" if key in merged else "") + status)
    if args.for_review:
        out += ["", f"Review effort: {task.get('review_effort', '—')} (core/reviewer's effort; one level lower for "
                    f"a low-risk task; this one is {env['risk']}).", "", "## Review checklist",
                "Give every line that isn't settled a verdict by its id, with `evidence` (where in the artifact) and, "
                "for a failed line, a `fix` (`task show <id> --checklist` prints them as JSON). pmos computes the "
                "pass: every core and must line holds, and the score (5 × the share of should lines that hold) is "
                f"{REVIEW_PASS_SCORE} or more.", ""]
        for line in review_checklist(task, mode, role):
            out.append(f"- [{'x' if line.get('settled') else ' '}] {checklist_line(line)}")
        if task.get("result"):
            out += ["", "## Producer self-check"]
            out += [f"- {'met' if s['met'] else 'NOT met'}: {s['criterion']}" + (f" · {s['note']}" if s.get("note") else "")
                    for s in task["result"].get("self_check", [])] or ["- (none recorded)"]
    print("\n".join(out))
    return 0


# Transitions only one command may make: `task move` can't make them.
OWNED_BY = {"in_review": "`pmos task review` (after `pmos task result`)",
            "awaiting_approval": "`pmos task review`", "approved": "`pmos task approve`"}


def cmd_task_move(args) -> int:
    task = load_task(args.id)
    if task["state"] == "in_review":
        raise PmosError(f"{args.id} is in_review; only {OWNED_BY['in_review']} moves it on")
    if args.state in ("awaiting_approval", "approved"):
        raise PmosError(f"only {OWNED_BY[args.state]} moves a task to {args.state}")
    if args.state == "done" and task["state"] == "approved":
        unsent = pending_send(task)
        if unsent:
            raise PmosError(f"{args.id} has pending send: {', '.join(a['idempotency_key'] for a in unsent)}; "
                            f"send each and record its receipt with `pmos action run {args.id} --receipt KEY=ID` "
                            f"(task move can't mark a send done)")
    if args.state == "running":
        pending = deps_pending(task)
        if pending:
            raise PmosError(f"{args.id} depends on unfinished task(s): {', '.join(pending)}")
        resolved = resolve_from_refs(task)
        if resolved is not None:
            task["inputs_resolved"] = resolved
    if args.state == "waiting":
        open_children = [c for c in task.get("children", []) if load_task(c)["state"] not in TERMINAL]
        if not open_children:
            raise PmosError(f"{args.id} has no unfinished children to wait for")
    if args.state == "revise":
        if task["state"] == "awaiting_approval":   # the PM's "change X": doesn't use up max_revisions
            task["change_requests"] = task.get("change_requests", 0) + 1
            task["revision_brief"] = {"from": "pm", "lines": [{"id": "pm-changes", "fix": args.note or "(no note)"}]}
        else:
            task["revisions"] = task.get("revisions", 0) + 1
    transition(task, args.state, args.by, args.note)
    write_board()
    print(f"{args.id}: {task['history'][-1]['from']} -> {args.state}")
    return 0


def task_tree_ids(task: dict) -> list[str]:
    """The task, its ancestors and its descendants: the outputs folders its artifacts may live in."""
    ids, cur = [task["envelope"]["id"]], task
    while cur["envelope"].get("parent"):
        cur = load_task(cur["envelope"]["parent"])
        ids.append(cur["envelope"]["id"])
    todo = list(task.get("children", []))
    while todo:
        cid = todo.pop()
        ids.append(cid)
        todo += load_task(cid).get("children", [])
    return ids


def artifacts_outside_outputs(task: dict, artifacts: list[dict]) -> list[str]:
    """Relative artifact refs must resolve inside <outputs>/<id>/ of the task's own tree; scheme refs
    (jira:, doc:, url: ...) point at systems of record and are allowed."""
    refs = [a["ref"] for a in artifacts if not re.match(r"^[a-z]+:", a["ref"])]
    if not refs:
        return []
    roots = [(path_of("outputs") / tid).resolve() for tid in task_tree_ids(task)]
    return [r for r in refs if not any((ROOT / r).resolve().is_relative_to(root) for root in roots)]


def check_actions_allowed(task: dict, actions: list[dict]) -> None:
    """An action's system must be granted to the mode at draft or write, and the action must be able to
    reach an approval gate: its own, or the parent's it rolls up to (approval_from)."""
    if not actions:
        return
    man = task_manifest(task)
    grants = man.get("grants") or {}
    ungranted = [f"{a['system']}.{a['op']} ({a['system']}: {grants.get(a['system'], 'not granted')})"
                 for a in actions if GRANT_LEVEL.get(grants.get(a["system"]), 0) < GRANT_LEVEL["draft"]]
    if ungranted:
        raise PmosError(f"{man.get('name')} may propose actions only on systems its grants give at draft or "
                        f"write; refused: {', '.join(ungranted)}")
    if task["envelope"]["approval"] == "none" and not task.get("approval_from"):
        raise PmosError(f"{task['envelope']['id']} has approval none, so nothing would ever approve its actions "
                        f"and they would never run. Drop the actions, or create the task with an approval rule.")


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
    outside = artifacts_outside_outputs(task, result.get("artifacts", []))
    if outside:
        raise PmosError(f"artifact(s) outside outputs/{args.id}/: {', '.join(outside)}. Write artifacts to "
                        f"{rel(path_of('outputs') / args.id)}/ (or this task's parent's or children's folder), "
                        f"or link a system with a scheme ref such as jira:STK-1")
    missing = [a["ref"] for a in result.get("artifacts", [])
               if not re.match(r"^[a-z]+:", a["ref"]) and not (ROOT / a["ref"]).exists()]
    if missing:
        raise PmosError(f"artifact(s) not found: {', '.join(missing)}")
    keys = [a["idempotency_key"] for a in result.get("actions", [])]
    if len(keys) != len(set(keys)):
        raise PmosError("idempotency_key values must be unique within a result")
    check_result_cheaply(task, result)          # summary length and this task's own budget

    env = task["envelope"]
    if result["status"] in ("done", "needs_approval") and task_manifest(task).get("merge_child_actions"):
        task["merged_actions"] = merge_child_actions(task, result)
        keys = [a["idempotency_key"] for a in result.get("actions", [])]
    check_actions_allowed(task, result.get("actions", []))   # merged child actions included
    check_outputs(result, task_mode(task)["manifest"])
    usd = float((result.get("usage") or {}).get("usd") or 0)
    check_tree_budget(task, usd)                # children draw down every ancestor's max_usd

    spent = usd_spent(task) + usd  # cumulative across resubmissions; read before the result is replaced
    task["result"] = result
    task["usd_spent"] = spent
    task["result_path"] = rel(path.resolve())
    task.pop("revision_brief", None)            # a new result answers the last brief
    to = {"done": "in_review", "needs_approval": "in_review", "blocked": "blocked", "failed": "failed"}[result["status"]]
    # Code lines first: the mode's done.must `code:` lines run before any Reviewer is spent.
    task["done_code"] = run_code_lines(task, result) if to == "in_review" else []
    code_failed = [r for r in task["done_code"] if not r["pass"]]
    note = "; ".join(result.get("open_questions", [])) if to == "blocked" else result["summary"][:200]
    trace(task, "result", status=result["status"], actions=len(keys), usage=result.get("usage"),
          code_lines={r["id"]: r["pass"] for r in task["done_code"]})
    transition(task, to, args.by, note)
    if code_failed:
        return code_lines_failed(task, code_failed, args.by)
    parent = load_task(env["parent"]) if env.get("parent") and to == "in_review" else None
    if parent and (task.get("approval_from") == parent["envelope"]["id"]
                   or (env["approval"] == "none" and parent["envelope"]["approval"] != "none")):
        # A gated child: its work is reviewed (and approved) once, inside the parent.
        to = "done"
        task["reviewed_with"] = parent["envelope"]["id"]
        transition(task, to, "pmos", f"review skipped: reviewed and approved with parent {parent['envelope']['id']}")
    write_board()
    print(f"{args.id}: result accepted -> {to}")
    return 0


def code_lines_failed(task: dict, failed: list[dict], by: str) -> int:
    """A result whose done code lines failed goes straight to revise (a failed check, counted against
    max_revisions), with each failing line's id and output as the note and the revision brief."""
    tid = task["envelope"]["id"]
    lines = [{"id": r["id"], "fix": f"make `{r['command']}` exit 0; it "
              + (f"exited {r['exit']}" if r.get("exit") is not None else "did not finish") + f": {tail(r['output'])}"}
             for r in failed]
    task["revision_brief"] = {"from": "code", "lines": lines}
    task["revisions"] = task.get("revisions", 0) + 1
    limit = config()["defaults"].get("max_revisions", 2)
    to = "revise" if task["revisions"] <= limit else "failed"
    note = "done code line(s) failed, no review run: " + "; ".join(f"{r['id']}: {tail(r['output'], 200)}" for r in failed)
    if to == "failed":
        note = f"failed its checks {task['revisions']} times: {note}"
    trace(task, "review", passed=False, score=None, failing=[r["id"] for r in failed], by="pmos", code_lines=True)
    transition(task, to, "pmos", note)
    write_board()
    print(f"{tid}: result accepted, but done code line(s) failed -> {to}")
    for r in failed:
        print(f"  - {r['id']}: `{r['command']}` " + (f"exited {r['exit']}" if r.get("exit") is not None else "did not finish")
              + f": {tail(r['output'])}")
    print(f"Fix them and resubmit (`pmos task show {tid}` lists them first).")
    return 1


def check_result_cheaply(task: dict, result: dict) -> None:
    """Checks code can make before any Reviewer is spent: summary length and the task's budget."""
    words = len(result["summary"].split())
    if words > SUMMARY_MAX_WORDS:
        raise PmosError(f"summary is {words} words; keep it to {SUMMARY_MAX_WORDS} (the CoS forwards it as-is)")
    usage, budget = result.get("usage") or {}, task["envelope"].get("budget") or {}
    over = []
    if usage.get("usd") is not None and budget.get("max_usd") is not None and usage["usd"] > budget["max_usd"]:
        over.append(f"usd {usage['usd']} > max_usd {budget['max_usd']}")
    if (usage.get("seconds") is not None and budget.get("max_minutes") is not None
            and usage["seconds"] > budget["max_minutes"] * 60):
        over.append(f"seconds {usage['seconds']} > max_minutes {budget['max_minutes']} x 60")
    if over and result["status"] != "failed":
        raise PmosError(f"over budget ({'; '.join(over)}). Submit status 'failed' with this usage, "
                        f"or ask the PM for a bigger budget")


def merge_child_actions(task: dict, result: dict) -> list[dict]:
    """Stage C in code: append the actions of done children whose approval rolled up to this task."""
    env, merged = task["envelope"], []
    have = {a["idempotency_key"] for a in result.get("actions", [])}
    for cid in task.get("children", []):
        child = load_task(cid)
        rolled_up = child.get("approval_from") == env["id"] or (
            child["envelope"]["approval"] == "none" and env["approval"] != "none")
        if child["state"] != "done" or not rolled_up:
            continue
        for a in (child.get("result") or {}).get("actions", []):
            if a["idempotency_key"] in have:
                continue
            result.setdefault("actions", []).append(a)
            have.add(a["idempotency_key"])
            merged.append({"from": cid, "idempotency_key": a["idempotency_key"]})
    return merged


def load_verdicts(task: dict, source: str) -> dict:
    """Read a verdicts file ('-' = stdin): one {id, pass, evidence, fix?} per checklist line that isn't settled.
    Returns the review lines (settled code lines included) and the score pmos computes from the should lines."""
    raw = sys.stdin.read() if source == "-" else Path(source).read_text(encoding="utf-8")
    try:
        verdicts = json.loads(raw)
    except json.JSONDecodeError as e:
        raise PmosError(f"--verdicts is not valid JSON: {e}")
    shape = '{"lines": [{"id": ..., "pass": true|false, "evidence": "<where in the artifact>", "fix": "<if failed>"}]}'
    if not isinstance(verdicts, dict) or not isinstance(verdicts.get("lines"), list):
        raise PmosError(f"--verdicts must be {shape}")
    if "score" in verdicts:
        print("note: the verdicts file's score is ignored; pmos computes it from the should lines", file=sys.stderr)
    checklist = review_checklist(task, task_mode(task), all_roles()[task["role"]])
    settled = {c["id"] for c in checklist if c.get("settled")}
    given, problems = {}, []
    for line in verdicts["lines"]:
        if not isinstance(line, dict) or not isinstance(line.get("id"), str) or not isinstance(line.get("pass"), bool):
            raise PmosError(f'each verdict needs an "id" and a boolean "pass": {line!r}')
        lid = line["id"]
        if lid in settled:
            problems.append(f"{lid} is settled (a code line pmos ran at task result); leave it out")
        if not str(line.get("evidence") or "").strip():
            problems.append(f"{lid} has no evidence (say where in the artifact: section, heading or line)")
        if not line["pass"] and not str(line.get("fix") or "").strip():
            problems.append(f"{lid} failed without a fix (say what must change)")
        given[lid] = line
    ids = [c["id"] for c in checklist if c["id"] not in settled]
    missing = [i for i in ids if i not in given]
    unknown = [i for i in given if i not in ids and i not in settled]
    if missing:
        problems.append(f"missing verdict for line(s): {', '.join(missing)}")
    if unknown:
        problems.append(f"unknown line(s): {', '.join(unknown)}")
    if problems:
        raise PmosError("verdicts must give every checklist line that isn't settled (`pmos task show <id> --checklist`) "
                        "a pass, evidence and, when it fails, a fix:\n  - " + "\n  - ".join(problems))
    lines = []
    for c in checklist:
        if c["id"] in settled:
            lines.append({"id": c["id"], "kind": c["kind"], "group": c["group"], "pass": True, "settled": True,
                          "evidence": f"pmos ran it at task result: exit {c.get('exit')}"})
            continue
        v = given[c["id"]]
        lines.append({"id": c["id"], "kind": c["kind"], "group": c["group"], "pass": v["pass"],
                      "evidence": str(v["evidence"]), **({"fix": str(v["fix"])} if v.get("fix") and not v["pass"] else {}),
                      **({"note": str(v["note"])} if v.get("note") else {})})
    should = [ln for ln in lines if ln["kind"] == "should"]
    score = round(5 * sum(ln["pass"] for ln in should) / len(should), 2) if should else 5.0
    return {"score": score, "lines": lines}


def cmd_task_review(args) -> int:
    task = load_task(args.id)
    if task["state"] != "in_review":
        raise PmosError(f"{args.id} is {task['state']}, not in_review")
    if not args.verdicts:
        raise PmosError("record per-line verdicts: `pmos task review <id> --verdicts FILE` (line ids from "
                        "`pmos task show <id> --checklist`). pmos computes the pass; --passed is no longer accepted")
    verdicts = load_verdicts(task, args.verdicts)
    failing = [line for line in verdicts["lines"] if not line["pass"]]
    score = verdicts["score"]
    blocking = [line for line in failing if line["kind"] in ("core", "must", "code")]
    passed = not blocking and score >= REVIEW_PASS_SCORE
    if args.passed is not None and (args.passed.lower() in ("true", "yes", "1", "pass")) != passed:
        print(f"warn: --passed {args.passed} ignored; pmos computed passed={str(passed).lower()} from the verdicts",
              file=sys.stderr)
    notes = list(args.note or []) + [f"{line['id']}: {line.get('fix') or line.get('note') or 'fails'}" for line in failing]
    review = {"passed": passed, "score": score, "notes": notes, "lines": verdicts["lines"]}
    # Stored in task state only: result.json stays the producer's file, so a resubmit after revise works.
    task["result"]["review"] = review
    trace(task, "review", passed=passed, score=score, failing=[line["id"] for line in failing], by=args.by)
    env, result = task["envelope"], task["result"]
    if passed:
        needs_ok = env["approval"] != "none" and (result.get("actions") or env["approval"] == "before_publish")
        to = "awaiting_approval" if needs_ok else "done"
        note = f"review passed (score {score:g})"
    else:
        task["revisions"] = task.get("revisions", 0) + 1
        limit = config()["defaults"].get("max_revisions", 2)
        to = "revise" if task["revisions"] <= limit else "failed"
        why = (f"{len(blocking)} core or must line(s) failed" if blocking
               else f"score {score:g} < {REVIEW_PASS_SCORE} from the should lines")
        note = f"review failed ({why}): " + "; ".join(notes)
        if to == "failed":
            note = f"failed review {task['revisions']} times: {note}"
        task["revision_brief"] = {"from": "review", "lines": [{"id": ln["id"], "fix": ln.get("fix") or "fails"}
                                                              for ln in failing]}
    transition(task, to, args.by, note)
    write_board()
    print(f"{args.id}: review {'passed' if passed else 'failed'} (score {score:g}, "
          f"{len(failing)} failing line(s){', ' + str(len(blocking)) + ' blocking' if blocking else ''}) -> {to}")
    return 0


def actions_digest(actions: list[dict]) -> str:
    return hashlib.sha256(json.dumps(actions, sort_keys=True).encode()).hexdigest()[:16]


def cmd_task_approve(args) -> int:
    task = load_task(args.id)
    if task["state"] != "awaiting_approval":
        raise PmosError(f"{args.id} is {task['state']}, not awaiting_approval")
    actions = task["result"].get("actions", [])
    digest = actions_digest(actions)
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
    roles = all_roles()
    for t in rows:
        e = t["envelope"]
        agent = delegate_target(roles[t["role"]]) if t["role"] in roles else "?"
        print(f"{e['id']}  {t['state']:<17} {t['mode_name']:<20} {t['role']:<22} {agent:<12} "
              f"{t.get('effort', '—'):<7} {t.get('dispatch', 'background'):<11} "
              f"{(t['history'][-1].get('note') or '')[:60]}")
    if not rows:
        print("(no tasks)")
    return 0


def cmd_task_state(args) -> int:
    task = load_task(args.id)
    print(json.dumps(task, indent=2, ensure_ascii=False) if args.json else task["state"])
    return 0


# --------------------------------------------------------------------------- actions
def external_systems() -> set[str]:
    """Systems whose actions reach people outside pmos: each needs a receipt before its task is done (SR1)."""
    return set(config().get("external_systems") or [])


def pending_send(task: dict) -> list[dict]:
    """The task's external actions that have no receipt yet (SR1, SR5)."""
    ext = external_systems()
    sent = {s["key"] for s in task.get("sent") or []}
    return [a for a in (task.get("result") or {}).get("actions", [])
            if a["system"] in ext and a["idempotency_key"] not in sent]


def parse_receipts(values: list[str] | None, actions: list[dict]) -> dict[str, str]:
    """--receipt KEY=RECEIPT: the key must be an external action of this task (SR3)."""
    by_key = {a["idempotency_key"]: a for a in actions}
    out: dict[str, str] = {}
    for raw in values or []:
        key, sep, receipt = raw.partition("=")
        if not sep or not receipt.strip():
            raise PmosError(f"--receipt wants KEY=RECEIPT, got '{raw}'")
        if key not in by_key:
            raise PmosError(f"--receipt {key}: the task has no action with that idempotency_key; receipt refused")
        a = by_key[key]
        if a["system"] not in external_systems():
            raise PmosError(f"--receipt {key}: {a['system']}.{a['op']} is not an external action, so it takes no receipt")
        out[key] = receipt.strip()
    return out


def handler_reply(stdout: str) -> dict:
    """A handler's reply: one JSON object on stdout (the last JSON line, if it prints anything else too)."""
    lines = [ln for ln in stdout.strip().splitlines() if ln.strip()]
    if not lines:
        return {}
    try:
        data = json.loads(lines[-1])
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def cmd_action_run(args) -> int:
    """Run an approved task's actions through the handlers its pack declares in pack.yaml `actions:`.

    A task is done only when every action is applied and every external action has a receipt (SR1-SR5).
    Exit: 0 done (or nothing left to do), 1 a handler failed or refused, 2 a send is still pending."""
    task = load_task(args.id)
    tid = task["envelope"]["id"]
    if task["state"] != "approved":
        raise PmosError(f"{tid} is {task['state']}; actions run only on an approved task")
    actions = (task.get("result") or {}).get("actions", [])
    approvals = task.get("approvals") or []
    if not approvals:
        raise PmosError(f"{tid} has no recorded approval")
    digest = actions_digest(actions)
    if digest != approvals[-1].get("actions_sha"):
        raise PmosError(f"{tid}'s actions changed since approval (sha {digest}, approved sha "
                        f"{approvals[-1].get('actions_sha')}); nothing was run. Send it back for approval.")
    if args.key and args.key not in {a["idempotency_key"] for a in actions}:
        raise PmosError(f"{tid} has no action with idempotency_key '{args.key}'")
    receipts = parse_receipts(args.receipt, actions)
    ext = external_systems()
    pack = packs().get(task["pack"])
    handlers = (pack["manifest"].get("actions") or {}) if pack else {}
    out_dir = path_of("outputs") / tid
    record_path = out_dir / "applied.json"
    record = load_json(record_path) if record_path.exists() else {}
    applied, sent = list(record.get("applied", [])), list(record.get("sent", []))
    done_keys = {a["key"] for a in applied} | {s["key"] for s in sent}
    recorded, skipped, failed, manual = [], [], [], []
    for a in actions:
        key, kind = a["idempotency_key"], f"{a['system']}.{a['op']}"
        external = a["system"] in ext
        if args.key and key != args.key:
            continue
        if key in done_keys:
            skipped.append({"key": key, "action": kind, "why": "already applied"})
            continue
        handler = handlers.get(kind)
        if not handler:
            if external and key in receipts:   # the Operator sent it with a tool and reports the receipt
                sent.append({"key": key, "receipt": receipts[key]})
                applied.append({"key": key, "action": kind, "receipt": receipts[key], "handler": None})
                done_keys.add(key)
            else:
                manual.append({"key": key, "action": kind, "preview": a.get("preview", "")})
            continue
        if failed:
            skipped.append({"key": key, "action": kind, "why": "an earlier action failed"})
            continue
        script, *fixed = shlex.split(handler)
        action_file = out_dir / "actions" / f"{re.sub(r'[^A-Za-z0-9_.-]', '_', key)}.json"
        payload = {"task_id": tid, "action": a}
        if key in receipts:
            payload["receipt"] = receipts[key]
        write_json(action_file, payload)
        proc = subprocess.run([sys.executable, str(pack["dir"] / script), *fixed, str(action_file)], cwd=ROOT,
                              capture_output=True, text=True, env={**os.environ, "PMOS_ROOT": str(ROOT)})
        entry = {"key": key, "action": kind, "handler": f"{task['pack']}: {handler}",
                 "output": (proc.stdout.strip() or proc.stderr.strip())[-2000:]}
        if proc.returncode != 0:
            failed.append(entry)
            continue
        if not external:
            applied.append(entry)
            done_keys.add(key)
            continue
        # the handler's receipt (SR2), else the one the Operator's tool returned and gave with --receipt (SR3)
        reply_receipt = handler_reply(proc.stdout).get("receipt") or receipts.get(key)
        if reply_receipt:                       # the handler confirms the send (SR2)
            entry["receipt"] = str(reply_receipt)
            applied.append(entry)
            sent.append({"key": key, "receipt": entry["receipt"]})
            done_keys.add(key)
        else:                                   # verified, not sent: the Operator still has to send it
            recorded.append(entry)
    pending = [a["idempotency_key"] for a in actions
               if a["system"] in ext and a["idempotency_key"] not in {s["key"] for s in sent}]
    out = {"task_id": tid, "applied": applied, "recorded": recorded, "sent": sent, "skipped": skipped,
           "failed": failed, "manual": manual, "pending_send": pending}
    write_json(record_path, out)
    task["sent"] = sent
    save_task(task)
    trace(task, "actions_run", by=args.by, applied=len(applied), sent=len(sent), failed=len(failed),
          manual=len(manual), pending_send=len(pending))
    all_done = {a["idempotency_key"] for a in actions} <= done_keys
    if not failed and not pending and all_done:
        transition(task, "done", args.by, f"{len(sent)} send(s) with receipts, {len(applied)} action(s) applied")
        write_board()
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 1 if failed else (2 if pending else 0)


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
        lines += ["| Task | Mode | Role | State | From | Updated |", "| --- | --- | --- | --- | --- | --- |"]
        for t in open_tasks:
            origin = t['envelope'].get('parent') or ":".join((t['envelope'].get('origin') or {}).values())
            lines.append(f"| {t['envelope']['id']} | {t['mode_name']} | {t['role']} | {t['state']} | "
                         f"{origin} | {t.get('updated_at', '')} |")
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


# --------------------------------------------------------------------------- stats
def percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    v = sorted(values)
    k = (len(v) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(v) - 1)
    return round(v[lo] + (v[hi] - v[lo]) * (k - lo), 1)


def compute_stats(records: list[dict]) -> dict:
    """Per mode and per effort level, from trace records: cost, latency, first-pass review rate and
    revise-after-approval rate."""
    per_task: dict[str, dict] = {}
    for r in sorted(records, key=lambda r: r.get("ts", "")):
        if not r.get("task_id"):       # a CoS reply (`pmos cos-turn`), summarised below
            continue
        t = per_task.setdefault(r["task_id"], {"mode": split_ref(r.get("mode") or "?")[0], "usd": 0.0,
                                               "created": None, "ready": None, "reviews": [],
                                               "awaited": False, "changed": False, "effort": None})
        t["effort"] = r.get("effort") or t["effort"]
        ts = dt.datetime.fromisoformat(r["ts"]) if r.get("ts") else None
        if r["event"] == "created":
            t["created"] = ts
        elif r["event"] == "result" and (r.get("usage") or {}).get("usd") is not None:
            t["usd"] += r["usage"]["usd"]
        elif r["event"] == "review":
            t["reviews"].append(bool(r.get("passed")))
        elif r["event"] == "transition":
            if r.get("to") in ("awaiting_approval", "done", "failed") and t["ready"] is None:
                t["ready"] = ts            # first point the PM could act on it
            if r.get("to") == "awaiting_approval":
                t["awaited"] = True
            if r.get("from") == "awaiting_approval" and r.get("to") == "revise":
                t["changed"] = True        # the PM asked for changes: the edit-rate proxy

    def rate(hits: int, n: int) -> float | None:
        return round(hits / n, 3) if n else None

    def summary(ts: list[dict]) -> dict:
        secs = [(t["ready"] - t["created"]).total_seconds() for t in ts if t["created"] and t["ready"]]
        reviewed = [t for t in ts if t["reviews"]]
        awaited = [t for t in ts if t["awaited"]]
        usd = round(sum(t["usd"] for t in ts), 4)
        return {"tasks": len(ts), "usd_total": usd, "usd_mean": round(usd / len(ts), 4),
                "p50_seconds": percentile(secs, 0.5), "p90_seconds": percentile(secs, 0.9),
                "first_pass_rate": rate(sum(1 for t in reviewed if t["reviews"][0]), len(reviewed)),
                "revise_after_approval_rate": rate(sum(1 for t in awaited if t["changed"]), len(awaited))}

    groups: dict[str, dict[str, list]] = {"modes": {}, "efforts": {}}
    for t in per_task.values():
        groups["modes"].setdefault(t["mode"], []).append(t)
        groups["efforts"].setdefault(t["effort"] or "unknown", []).append(t)
    order = {lvl: i for i, lvl in enumerate(EFFORT_LEVELS)}
    turns = [r for r in records if r.get("event") == "cos_turn"]
    secs, calls = [float(r.get("seconds") or 0) for r in turns], [float(r.get("tool_calls") or 0) for r in turns]
    limit = (config().get("cos") or {}).get("inline_max_tool_calls", 2)
    cos = {"turns": len(turns), "p50_seconds": percentile(secs, 0.5), "p90_seconds": percentile(secs, 0.9),
           "p50_tool_calls": percentile(calls, 0.5), "p90_tool_calls": percentile(calls, 0.9),
           "max_tool_calls": max(calls) if calls else None, "inline_max_tool_calls": limit,
           "over_inline_limit": sum(1 for c in calls if c > limit)}
    return {"modes": {k: summary(v) for k, v in sorted(groups["modes"].items())},
            "efforts": {k: summary(v) for k, v in sorted(groups["efforts"].items(), key=lambda kv: order.get(kv[0], 9))},
            "cos": cos}


def parse_ts(raw: str, flag: str) -> dt.datetime:
    try:
        t = dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        raise PmosError(f"{flag}: '{raw}' is not an ISO 8601 time, e.g. 2026-10-24T10:00:00+00:00")
    return t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)


def cmd_cos_turn(args) -> int:
    """One CoS reply, logged to the traces: how long the PM waited and how many tool calls came first."""
    started = parse_ts(args.started, "--started")
    replied = parse_ts(args.replied, "--replied") if args.replied else dt.datetime.now(dt.timezone.utc)
    if replied < started:
        raise PmosError(f"--replied {replied.isoformat()} is before --started {started.isoformat()}")
    if args.tool_calls < 0:
        raise PmosError("--tool-calls can't be negative")
    seconds = round((replied - started).total_seconds(), 1)
    limit = (config().get("cos") or {}).get("inline_max_tool_calls", 2)
    record = {"ts": now(), "event": "cos_turn", "started": started.isoformat(), "replied": replied.isoformat(),
              "seconds": seconds, "tool_calls": args.tool_calls, "inline_max_tool_calls": limit, "note": args.note}
    traces = path_of("traces")
    traces.mkdir(parents=True, exist_ok=True)
    with open(traces / f"{dt.date.today():%Y-%m}.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(f"logged CoS reply: {seconds:g} s, {args.tool_calls} tool call(s)"
          + (f" (over cos.inline_max_tool_calls {limit})" if args.tool_calls > limit else ""))
    return 0


def cmd_stats(args) -> int:
    records = []
    traces = path_of("traces")
    for f in sorted(traces.glob("*.jsonl")) if traces.exists() else []:
        for line in f.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    if args.mode:
        records = [r for r in records if split_ref(r.get("mode") or "")[0] == args.mode]
    stats = compute_stats(records)
    if args.json:
        print(json.dumps(stats, indent=2))
        return 0

    def fmt(v, pct=False):
        return "—" if v is None else (f"{v:.0%}" if pct else f"{v:g}" if isinstance(v, float) else f"{v}")
    if not stats["modes"] and not stats["cos"]["turns"]:
        print("(no traces yet)")
        return 0
    c = stats["cos"]
    if c["turns"]:
        print("| CoS replies | p50 s | p90 s | p50 tool calls | p90 tool calls | Over inline limit |")
        print("| --- | --- | --- | --- | --- | --- |")
        print(f"| {c['turns']} | {fmt(c['p50_seconds'])} | {fmt(c['p90_seconds'])} | {fmt(c['p50_tool_calls'])} | "
              f"{fmt(c['p90_tool_calls'])} | {c['over_inline_limit']} (> {c['inline_max_tool_calls']}) |")
        print()
    for title, key in (("Mode", "modes"), ("Effort", "efforts")):
        if not stats[key]:
            continue
        print(f"| {title} | Tasks | USD total | USD mean | p50 s | p90 s | First-pass | Revised after approval |")
        print("| --- | --- | --- | --- | --- | --- | --- | --- |")
        for name, m in stats[key].items():
            print(f"| {name} | {m['tasks']} | {m['usd_total']} | {m['usd_mean']} | {fmt(m['p50_seconds'])} | "
                  f"{fmt(m['p90_seconds'])} | {fmt(m['first_pass_rate'], True)} | "
                  f"{fmt(m['revise_after_approval_rate'], True)} |")
        print()
    return 0


# --------------------------------------------------------------------------- render
def all_skill_sources() -> list[tuple[str, Path, Path | None]]:
    """(rendered skill name, SKILL.md path, mode dir or None) for every installed pack."""
    items = [(render_name(sid), path, None) for sid, path in all_skills().items()]
    for m in discover_modes():
        man = m["manifest"]
        items.append((render_name(man["name"]), m["dir"] / man.get("skill", "SKILL.md"), m["dir"]))
    return items


def cos_agents() -> set[str]:
    """The agents the cos_pack defines: the Chief of Staff, which runs from AGENTS.md."""
    return {name for name, (_m, _b, _p, pack) in all_agents().items() if pack == config().get("cos_pack")}


def render_agents_md() -> int:
    write_catalog()
    print("AGENTS.md regenerated from the cos pack")
    return 0


def agent_renders(name: str, meta: dict) -> list[tuple[str, str, str]]:
    """(rendered name, tier, description) per agent. An agent that lists `tiers:` is also rendered once
    per tier as `<name>-<tier>`, so a role's tier reaches the model (`task show` prints `delegate to:`)."""
    out = [(name, meta["tier"], meta["description"])]
    for tier in meta.get("tiers") or []:
        out.append((f"{name}-{tier}", tier, f"{meta['description']} Runs on the {tier} tier: use it for a task "
                                            f"whose `task show` says `delegate to: {name}-{tier}`."))
    return out


def render_claude_code() -> int:
    ad = config()["adapters"]["claude-code"]
    tiers = config()["tiers"][ad["provider"]]
    warnings = []
    write_catalog()

    claude_md = ROOT / "CLAUDE.md"
    if not claude_md.exists():
        claude_md.write_text("@AGENTS.md\n\n<!-- Generated by `pmos render claude-code`. "
                             "Edit packs/<cos pack>/COS.md, not this file. -->\n", encoding="utf-8")
    elif "@AGENTS.md" not in claude_md.read_text(encoding="utf-8"):
        warnings.append("CLAUDE.md exists but doesn't import @AGENTS.md; add that line")

    agents_out = ROOT / ad["agents_dir"]
    agents_out.mkdir(parents=True, exist_ok=True)
    count = 0
    for name, (meta, body, src, _pack) in all_agents().items():
        if name in cos_agents():
            continue  # the CoS is the main session; it reads AGENTS.md via CLAUDE.md
        mapped, unmapped = [], []
        for g in meta.get("grants", []):
            tools = ad.get("grants_to_tools", {}).get(g)
            (mapped.extend(tools) if tools else unmapped.append(g))
        if unmapped:
            warnings.append(f"agent '{name}': grants {unmapped} have no tool mapping in pm-os.yaml; it inherits "
                            f"all tools, so the permission line is NOT enforced for it yet")
        effort, _ = resolve_setting("effort", None, None, {"agent": name})
        dispatch, _ = resolve_setting("dispatch", None, None, {"agent": name})
        for out_name, tier, description in agent_renders(name, meta):
            model = ad["aliases"][tier] if ad.get("model_field", "alias") == "alias" else tiers[tier]
            lines = ["---", f"name: {out_name}", f"description: {description}", f"model: {model}"]
            if not unmapped:
                lines.append(f"tools: {', '.join(dict.fromkeys(mapped))}")
            if ad.get("supports_effort"):       # only when the harness has such a field (pm-os.yaml says so)
                lines.append(f"effort: {effort_param(ad['provider'], effort)[1]}")
            if ad.get("supports_background"):
                lines.append(f"{ad.get('background_field') or 'background'}: {str(dispatch == 'background').lower()}")
            lines += ["---", f"<!-- Generated by `pmos render claude-code` from {rel(src)}. Edit the source, then re-render. -->",
                      "", body.strip(), ""]
            (agents_out / f"{out_name}.md").write_text("\n".join(lines), encoding="utf-8")
            count += 1

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
        (target / "SKILL.md").write_text(with_skill_name(skill_md, name), encoding="utf-8")
        if mode_dir is not None:
            shutil.copy2(mode_dir / "mode.yaml", target / "mode.yaml")
        names.append(name)
    marker.write_text("\n".join(names) + "\n", encoding="utf-8")
    lock_lines = render_cos_lock(ad)

    for w in warnings:
        print(f"warn: {w}")
    print(f"claude-code: {count} agent(s) -> {ad['agents_dir']}, {len(names)} skill(s) -> {ad['skills_dir']}, "
          f"CLAUDE.md -> AGENTS.md")
    for line in lock_lines:
        print(line)
    if not ad.get("supports_effort"):
        print("note: effort not written to subagent frontmatter (adapters.claude-code.supports_effort is false): "
              "subagents run at the session default; `task show` still prints each task's effort")
    if not ad.get("supports_background"):
        print("note: dispatch not written to subagent frontmatter (adapters.claude-code.supports_background is "
              "false): it is carried by `task show` (`run:`) and COS.md")
    return 0


def cos_lock_rules(ad: dict) -> dict[str, list[str]]:
    """Claude Code permission rules (`permissions.allow` / `permissions.deny`, the documented keys) that
    keep the session to pmos, the pack scripts and reads: no file edits outside the outputs folder (an
    `Edit(path)` rule covers every built-in file-writing tool) and no write-granted MCP tools."""
    outputs = path_of("outputs")
    keep = outputs.relative_to(ROOT).parts[0] if outputs.is_relative_to(ROOT) else None
    deny = [f"Edit(/{p.name}/**)" if p.is_dir() else f"Edit(/{p.name})"
            for p in sorted(ROOT.iterdir()) if p.name != keep]
    for grant, tools in (ad.get("grants_to_tools") or {}).items():
        if grant.split(":")[-1] not in ("read", "pmos"):          # write, send, …: a change to some system
            deny += [t for t in tools or [] if str(t).startswith("mcp__")]
    allow = ["Bash(python scripts/pmos.py *)"]
    for name, p in packs().items():
        if name != CORE:
            allow += [f"Bash(python {rel(p['dir'] / s)} *)" for s in view_scripts(pack_view(name)) if s.endswith(".py")]
    return {"allow": list(dict.fromkeys(allow)), "deny": list(dict.fromkeys(deny))}


def render_cos_lock(ad: dict) -> list[str]:
    """adapters.claude-code.lock_cos: merge pmos's rules into .claude/settings.json (true), or take them out
    again (false). Rules pmos added are listed in .claude/.pmos-settings.json, so the PM's own stay."""
    settings, mine = ROOT / ".claude" / "settings.json", ROOT / ".claude" / ".pmos-settings.json"
    previous = load_json(mine) if mine.exists() else {}
    data = load_json(settings) if settings.exists() else None
    if data is not None:
        perms = data.get("permissions") or {}
        for key in ("allow", "deny"):
            if key in perms:
                perms[key] = [r for r in perms[key] if r not in (previous.get(key) or [])]
                if not perms[key]:
                    del perms[key]
        if perms:
            data["permissions"] = perms
        else:
            data.pop("permissions", None)
    if not ad.get("lock_cos"):
        if previous and data is not None:
            write_json(settings, data)
        mine.unlink(missing_ok=True)
        return []
    rules = cos_lock_rules(ad)
    data = data or {}
    perms = data.setdefault("permissions", {})
    for key in ("allow", "deny"):
        perms[key] = list(dict.fromkeys([*(perms.get(key) or []), *rules[key]]))
    write_json(settings, data)
    write_json(mine, rules)
    mcp = [r for r in rules["deny"] if r.startswith("mcp__")]
    return [f"lock_cos: on — {rel(settings)} denies file edits outside {rel(path_of('outputs'))}/ "
            f"({len(rules['deny']) - len(mcp)} rule(s)) and {len(mcp)} write-granted MCP tool(s), and allows pmos "
            f"and {len(rules['allow']) - 1} pack script(s); reads stay allowed",
            "warn: lock_cos also blocks you (the PM) from having Claude edit files in this session; set "
            "adapters.claude-code.lock_cos: false and re-render to edit here, or edit in another session",
            "note: Claude Code documents no per-agent scope for these rules, so subagents started from this session "
            "get them too: Workers still write under outputs/, but the Operator can't use the denied MCP write tools; "
            "run approved actions that have no pack handler from a session without the lock. Re-render after "
            "adding top-level files or folders."]


def render_generic() -> int:
    ad = config()["adapters"]["generic"]
    tiers = config()["tiers"][ad["provider"]]
    out = ROOT / ad["out_dir"]
    out.mkdir(parents=True, exist_ok=True)
    write_catalog()
    skill_index = ["## Skills available", "", "Load a skill by reading its SKILL.md when a step needs it.", ""]
    for name, path, _ in all_skill_sources():
        meta, _ = frontmatter(path)
        skill_index.append(f"- `{name}` ({rel(path)}): {meta.get('description', '')}")
    models, grants = {"agents": {}, "roles": {}}, {}
    for name, (meta, body, _src, _pack) in all_agents().items():
        prompt = (ROOT / "AGENTS.md").read_text(encoding="utf-8") if name in cos_agents() else body.strip() + "\n\n" + "\n".join(skill_index)
        effort, _ = resolve_setting("effort", None, None, {"agent": name})
        dispatch, _ = resolve_setting("dispatch", None, None, {"agent": name})
        param, value = effort_param(ad["provider"], effort)
        for out_name, tier, _desc in agent_renders(name, meta):
            (out / f"{out_name}.system.md").write_text(prompt + "\n", encoding="utf-8")
            models["agents"][out_name] = {"tier": tier, "model": tiers.get(tier, ""), "effort": effort,
                                          "provider_param": param, "provider_value": value, "dispatch": dispatch}
            grants[out_name] = meta.get("grants", [])
    for fq, r in all_roles().items():
        effort, _ = resolve_setting("effort", None, None, r)
        dispatch, _ = resolve_setting("dispatch", None, None, r)
        param, value = effort_param(ad["provider"], effort)
        models["roles"][fq] = {"agent": delegate_target(r), "tier": r["tier"], "model": tiers.get(r["tier"], ""),
                               "effort": effort, "provider_param": param, "provider_value": value,
                               "dispatch": dispatch}
    write_json(out / "models.json", models)
    write_json(out / "grants.json", grants)
    shutil.copy2(path_of("state") / "catalog.md", out / "catalog.md")
    print(f"generic: {len(models['agents'])} system prompt(s), models.json, grants.json -> {ad['out_dir']}")
    return 0


def cmd_render(args) -> int:
    return {"agents-md": render_agents_md, "claude-code": render_claude_code, "generic": render_generic}[args.adapter]()


# --------------------------------------------------------------------------- eval@1: cases and coverage
CORE_CASES = ROOT / "evals" / "framework"   # core's conformance folder: one subfolder per group
CORE_CASE_SKIP = {"fixtures", "findings"}


def pack_view(name: str | None = None, d: Path | None = None) -> dict:
    """What eval@1 needs to know about a pack: its dir, manifest and modes. NAME = an installed pack (or
    core); D = a pack folder that need not be installed (e.g. a staged pack)."""
    if name == CORE:
        return {"name": CORE, "dir": ROOT, "manifest": {}, "modes": [], "core": True}
    if d is None:
        p = packs()[name]
        d, man = p["dir"], p["manifest"]
    else:
        d = Path(d).resolve()
        if not (d / "pack.yaml").exists():
            raise PmosError(f"no pack.yaml in {d}")
        man = load_yaml(d / "pack.yaml") or {}
    name = man.get("name") or name
    exported = {q_role(n, name) for n in (man.get("exports") or {}).get("modes") or []}
    modes = []
    for mf in sorted((d / "modes").glob("*/mode.yaml")):
        mm = load_yaml(mf) or {}
        modes.append({"name": mm.get("name"), "dir": mf.parent, "manifest": mm,
                      "evals": mf.parent / str(mm.get("evals") or "evals/"), "exported": mm.get("name") in exported})
    return {"name": name, "dir": d, "manifest": man, "modes": modes, "core": False}


def view_scripts(v: dict) -> list[str]:
    """Scripts a pack ships, relative to the pack: scripts/** and modes/*/scripts/** (core: scripts/*.py)."""
    if v["core"]:
        return [f"scripts/{p.name}" for p in sorted((ROOT / "scripts").glob("*.py"))]
    d, out = v["dir"], []
    for base in [d / "scripts", *sorted((d / "modes").glob("*/scripts"))]:
        for f in sorted(base.rglob("*")) if base.is_dir() else []:
            if f.is_file() and "__pycache__" not in f.parts and not f.name.startswith(".") and f.suffix != ".pyc":
                out.append(f.relative_to(d).as_posix())
    return out


def view_standards(v: dict) -> list[str]:
    """The names of a pack's document standards (standards/<name>.yaml); core has none."""
    d = v["dir"] / "standards"
    return [] if v["core"] or not d.is_dir() else [f.stem for f in sorted(d.glob("*.yaml"))]


def view_channels(v: dict) -> list[str]:
    """The names of a pack's channels (channels/<name>/channel.yaml); core has none."""
    return [] if v["core"] else [f.parent.name for f in sorted((v["dir"] / "channels").glob("*/channel.yaml"))]


def view_features(v: dict) -> dict[str, str]:
    """feature ref -> what covers it: exported modes need a golden and a failure-path case, scripts and
    action handlers a conformance case, a standard a passing and a failure-path conformance case, a
    router a workflow case."""
    out = {f"mode:{m['name']}": "golden + failure" for m in v["modes"] if m["exported"]}
    out.update({f"script:{s}": "conformance" for s in view_scripts(v)})
    out.update({f"standard:{v['name']}:{s}": "conformance pass + failure" for s in view_standards(v)})
    out.update({f"channel:{v['name']}/{c}": "conformance" for c in view_channels(v)})
    out.update({f"action:{k}": "conformance" for k in (v["manifest"].get("actions") or {})})
    if v["manifest"].get("router"):
        out[f"router:{q_role(v['manifest']['router'], v['name'])}"] = "workflow"
    return out


def view_refs(v: dict) -> set[str]:
    """Every ref a case of this pack may cover: its features, any of its modes, and its principles."""
    refs = set(view_features(v)) | {f"mode:{m['name']}" for m in v["modes"]}
    base = (ROOT / config()["paths"]["skills"]) if v["core"] else v["dir"] / "skills"
    refs |= {f"principle:{v['name']}:{p.parent.name}" for p in (base / "principles").glob("*/SKILL.md")}
    return refs


def view_case_files(v: dict) -> list[tuple[Path, str, str | None]]:
    """(file, where, mode): where = core (evals/framework/<group>/), conformance, workflows or golden (a mode's evals/)."""
    if v["core"]:
        return [(f, "core", None) for f in sorted(CORE_CASES.glob("*/*.yaml")) if f.parent.name not in CORE_CASE_SKIP]
    out = []
    for m in v["modes"]:
        out += [(f, "golden", m["name"]) for f in sorted(m["evals"].glob("*.json"))]
    ev = v["dir"] / "evals"
    out += [(f, "conformance", None) for f in sorted([*ev.glob("conformance/*.yaml"), *ev.glob("conformance/*.yml")])]
    out += [(f, "workflows", None) for f in sorted(ev.glob("workflows/*.json"))]
    return out


def load_view_cases(v: dict) -> tuple[list[dict], list[str]]:
    """The pack's eval@1 cases, each checked against contracts/eval.schema.json, its folder's kind, and
    the pack's own features (a pack's evals are self-contained)."""
    cases, errors, names = [], [], {}
    refs, modes = view_refs(v), {m["name"] for m in v["modes"]}
    for f, where, mode in view_case_files(v):
        where_rel = rel(f)
        try:
            data = load_json(f) if f.suffix == ".json" else load_yaml(f)
        except (json.JSONDecodeError, yaml.YAMLError) as e:
            errors.append(f"{where_rel}: not valid {f.suffix[1:]}: {str(e).splitlines()[0]}")
            continue
        if not isinstance(data, dict):
            errors.append(f"{where_rel}: an eval case is an object")
            continue
        errs = schema_errors(data, "eval", where_rel)
        want = "conformance" if where in ("core", "conformance") else "golden"
        if data.get("kind") in ("conformance", "golden") and data["kind"] != want:
            folder = {"core": "evals/framework/<group>/", "conformance": "evals/conformance/",
                      "workflows": "evals/workflows/", "golden": "a mode's evals/"}[where]
            errs.append(f"{where_rel}: kind is {data['kind']}, but cases in {folder} are kind {want}")
        for ref in data.get("covers") or []:
            if isinstance(ref, str) and ref not in refs:
                errs.append(f"{where_rel}: covers {ref}, which pack '{v['name']}' doesn't have (a pack's cases "
                            f"cover its own modes, scripts, actions, router and principles)")
        env_mode = split_ref(str((data.get("envelope") or {}).get("mode", "")))[0]
        if want == "golden" and env_mode and env_mode not in modes:
            errs.append(f"{where_rel}: envelope mode {env_mode} is not a mode of pack '{v['name']}'")
        if want == "conformance" and data.get("name"):
            if data["name"] in names:
                errs.append(f"{where_rel}: case name '{data['name']}' is also used by {names[data['name']]}")
            names[data["name"]] = where_rel
        errors += errs
        cases.append({**data, "_file": f, "_where": where, "_mode": mode, "_group": f.parent.name,
                      "_valid": not errs})
    return cases, errors


def coverage(v: dict, cases: list[dict]) -> tuple[list[tuple[str, str, list[str]]], list[str]]:
    """(rows, gaps): per feature, the cases covering it; and a message per missing case, naming the folder."""
    base = rel(v["dir"]) if not v["core"] else None
    conf_dir = "evals/framework/<group>/" if v["core"] else f"{base}/evals/conformance/"
    rows, gaps = [], []
    mode_evals = {f"mode:{m['name']}": rel(m["evals"]).rstrip("/") + "/" for m in v["modes"]}

    def covering(ref, pick):
        return [c.get("name") or c["_file"].name for c in cases if ref in (c.get("covers") or []) and pick(c)]

    for ref, need in view_features(v).items():
        if need == "golden + failure":
            golden = covering(ref, lambda c: c.get("kind") == "golden" and not c.get("failure"))
            failure = covering(ref, lambda c: bool(c.get("failure")))
            rows.append((ref, need, golden + [f"{n} (failure)" for n in failure]))
            if not golden:
                gaps.append(f"coverage: {ref} has no golden case; add one to {mode_evals[ref]}")
            if not failure:
                gaps.append(f"coverage: {ref} has no failure-path case (`failure: true`); add a golden case to "
                            f"{mode_evals[ref]} or a conformance case to {conf_dir}")
        elif need == "conformance pass + failure":
            passing = covering(ref, lambda c: c.get("kind") == "conformance" and not c.get("failure"))
            failing = covering(ref, lambda c: c.get("kind") == "conformance" and bool(c.get("failure")))
            rows.append((ref, need, passing + [f"{n} (failure)" for n in failing]))
            if not passing:
                gaps.append(f"coverage: {ref} has no passing case (check_doc.py on a document that meets it); "
                            f"add one to {conf_dir}")
            if not failing:
                gaps.append(f"coverage: {ref} has no failure-path case (`failure: true`, a document that fails it); "
                            f"add one to {conf_dir}")
        elif need == "conformance":
            hits = covering(ref, lambda c: c.get("kind") == "conformance")
            rows.append((ref, need, hits))
            if not hits:
                gaps.append(f"coverage: {ref} has no conformance case; add one to {conf_dir}")
        else:
            hits = covering(ref, lambda c: c["_where"] == "workflows")
            rows.append((ref, need, hits))
            if not hits:
                gaps.append(f"coverage: {ref} has no workflow case; add one to {base}/evals/workflows/")
    return rows, gaps


def eval_errors(name: str) -> list[str]:
    """Case errors and coverage gaps for an installed pack (or core): part of admission and `validate`."""
    v = pack_view(name)
    cases, errors = load_view_cases(v)
    return errors + coverage(v, cases)[1]


# --------------------------------------------------------------------------- eval@1: sandbox and runners
def framework_eval_module():
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import framework_eval
    return framework_eval


def clean_env(**extra) -> dict:
    """The environment for a nested pmos run: inherited PMOS_* overrides dropped (the conformance chain kept)."""
    keep = "PMOS_CONFORMANCE_CHAIN"
    return {**{k: v for k, v in os.environ.items() if not k.startswith("PMOS_") or k == keep}, **extra}


def eval_sandbox(name: str, candidate: Path, man: dict) -> tuple[Path, str]:
    """A temporary copy of the repo holding only core, the packs NAME depends on (transitively), the CoS
    pack and NAME itself (installed from CANDIDATE), so a pack's evals can assume nothing else.
    Returns (copy, the pack's path in it)."""
    fe = framework_eval_module()
    copy = Path(tempfile.mkdtemp(prefix="pmos-sandbox-")) / "repo"
    shutil.copytree(ROOT, copy, ignore=fe.ignore_for(ROOT), symlinks=True)
    for d in ("traces", "outputs", "state"):
        (copy / d).mkdir(exist_ok=True)
    entries = list(((load_yaml(packs_file()) if packs_file().exists() else {}) or {}).get("packs") or [])
    keep, todo = {config().get("cos_pack")}, [split_ref(x)[0] for x in man.get("depends") or []]
    while todo:
        dep = todo.pop()
        if dep in keep or dep not in packs():
            continue
        keep.add(dep)
        todo += [split_ref(x)[0] for x in packs()[dep]["manifest"].get("depends") or []]
    keep.discard(name)
    existing = next((e for e in entries if e["name"] == name), None)
    dest_rel = existing["path"] if existing and not os.path.isabs(existing["path"]) else f"packs/{name}"
    same = bool(existing and (ROOT / dest_rel).resolve() == candidate.resolve()
                and str(existing.get("version")) == str(man.get("version")))
    kept = [e for e in entries if e["name"] in keep or (same and e["name"] == name)]
    for e in entries:   # packs outside the sandbox are removed, so a case can't lean on them
        if e not in kept and e["name"] != name and not os.path.isabs(e["path"]):
            shutil.rmtree(copy / e["path"], ignore_errors=True)
    (copy / config()["paths"]["packs_file"]).write_text(
        "# Eval sandbox: core, the CoS pack, and the pack under test with its depends.\n"
        + yaml.safe_dump({"packs": kept}, sort_keys=False), encoding="utf-8")
    if not same:
        dest = copy / dest_rel
        shutil.rmtree(dest, ignore_errors=True)
        shutil.copytree(candidate, dest, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        source = (existing or {}).get("source", "local")
        proc = subprocess.run([sys.executable, "scripts/pmos.py", "pack", "add", dest_rel, "--approve-grants",
                               "--source", source], cwd=copy, capture_output=True, text=True,
                              env=clean_env(PMOS_EVAL_SANDBOX="1"))
        if proc.returncode != 0:
            shutil.rmtree(copy.parent, ignore_errors=True)
            raise PmosError(f"eval sandbox: installing '{name}' failed:\n{(proc.stdout + proc.stderr).strip()}")
    return copy, dest_rel


def runner_cases(v: dict, cases: list[dict]) -> list[dict]:
    """eval@1 conformance cases in the shape scripts/framework_eval.py runs."""
    out = []
    for c in cases:
        case = {k: val for k, val in c.items() if not k.startswith("_")}
        case["_file"] = rel(c["_file"])
        case.setdefault("owner", c["_group"] if v["core"] else v["name"])
        out.append(case)
    return out


def run_conformance(v: dict, cases: list[dict], candidate: Path | None = None) -> list[dict]:
    """Run conformance cases: core's in copies of the repo, a pack's in copies of its sandbox."""
    fe = framework_eval_module()
    if not cases:
        return []
    if v["core"]:
        return fe.run_cases(runner_cases(v, cases), ROOT, CORE_CASES, fe.CORE_CTX)
    copy, dest_rel = eval_sandbox(v["name"], candidate or v["dir"], v["manifest"])
    try:
        ctx = {"pack": v["name"], "pack_rel": dest_rel, "fx_rel": f"{dest_rel}/evals/fixtures", "sync_fixtures": False}
        return fe.run_cases(runner_cases(v, cases), copy, None, ctx)
    finally:
        shutil.rmtree(copy.parent, ignore_errors=True)


def case_record(rec: dict) -> dict:
    """framework_eval's record -> an eval-result@1 case."""
    return {"pack": rec["pack"], "name": rec["name"] or "?", "kind": rec.get("kind", "conformance"),
            "file": rec.get("file") or "", "covers": rec.get("covers") or [], "failure_path": bool(rec.get("failure_path")),
            "result": rec["result"], "first_failure": rec.get("failure"), "seconds": rec.get("seconds") or 0.0,
            "usd": None, "owner": rec.get("owner"), "finding": rec.get("finding"), "regression": bool(rec.get("regression"))}


def golden_prompt(spec: dict, man: dict, role: dict, case_dir: Path, case_name: str) -> tuple[list[str], list[str]]:
    env = spec["envelope"]
    new_cmd = (f"python scripts/pmos.py task new --mode {env['mode']} --verb {env['verb']} "
               f"--inputs '{json.dumps(env['inputs'])}' --risk {env.get('risk', 'medium')} "
               f"--approval {env.get('approval', 'none')}"
               + (f" --effort {env['effort']}" if env.get("effort") else "")
               + "".join(f" --acceptance {json.dumps(a)}" for a in env.get("acceptance", [])))
    fixtures, gates = spec.get("fixtures", {}), spec.get("gates") or []
    prompt = [
        f"# pm-os eval: {man['name']} · {case_name}", "",
        "You are running a golden task in an isolated state directory; PMOS_OUTPUTS_DIR is set, so write "
        "artifacts to the outputs folder `task show` prints, not to outputs/.",
        "1. Create the task:", "", "```", new_cmd, "```", "",
        f"2. Act as the `{delegate_target(role)}` agent (agents/{role['agent']}.md) on the printed task id, "
        "end to end.",
        "   Where a step reads Jira or calendars, use the fixtures below instead of live systems.",
    ]
    if gates:
        prompt += [
            "   Run every child task the mode creates the same way, as the worker its `task show` names; "
            "pmos re-queues the parent when they finish (`python scripts/pmos.py task list --state queued`).",
            "   Where a mode pauses for the PM (a gate: a `blocked` result with an open question), answer it "
            "with the next entry under Gate answers: `python scripts/pmos.py task move <id> queued --note "
            "\"PM: <answer>\"`, then carry on.",
            "   Finish when the task's final result is submitted (`in_review`); don't review or approve it.", "",
            "## Gate answers", "", *[f"{i}. {g}" for i, g in enumerate(gates, 1)], "",
        ]
    else:
        prompt += ["   Where a mode pauses for the PM (a gate), stop there.", ""]
    if fixtures:
        prompt += ["## Fixtures", "", "```json", json.dumps(fixtures, indent=2), "```", ""]
    return prompt, []


def golden_grader(spec: dict, mode: dict, role: dict, case_dir: Path, case_name: str) -> list[str]:
    """grader.md: the case's `expect` lines (expect-N), or without them the mode's done.must lines, plus the core
    principles, all to hold; then the should lines that set the score. Ids match `task show --checklist`."""
    env = spec["envelope"]
    fake = {"envelope": {"id": "golden", "acceptance": env.get("acceptance") or [], "instructions": None},
            "children": []}
    lines = review_checklist(fake, mode, role)
    expect = spec.get("expect")
    must = [c for c in lines if c["kind"] == "core"]
    if expect:
        must += [{"id": f"expect-{i}", "kind": "expect", "text": e} for i, e in enumerate(expect, 1)]
        heading = "## Must hold (the case's expect lines and the core principles)"
    else:
        must += [c for c in lines if c["kind"] in ("must", "code")]
        heading = "## Must hold (the mode's done.must, the task's acceptance and the core principles; this case sets no expect)"
    should = [c for c in lines if c["kind"] == "should"]
    out = [f"# Grader: {mode['manifest']['name']} · {case_name}", "",
           f"Score the worker's output ({rel(case_dir / 'outputs')}/<task id>/, and the run log output.md) against "
           f"each line. Pass = every line under Must hold is met and at least {REVIEW_PASS_SCORE / 5:.0%} of the score "
           f"lines are.",
           'Print only JSON: {"passed": true|false, "lines": [{"id": "<line id>", "line": "<the line>", '
           '"pass": true|false, "note": "<why>"}]}', "", heading, ""]
    out += [f"- [ ] {checklist_line(c, state=False)}" for c in must]
    out += ["", "## Score lines (done.should, cited principles, the role's rubric)", ""]
    out += [f"- [ ] {checklist_line(c, state=False)}" for c in should] or ["(none)"]
    return out


def run_golden(v: dict, cases: list[dict], state: dict, log) -> list[dict]:
    """Render each golden case to build/evals/<pack>__<mode or workflows>/<case>/; with eval.command set, run
    it in isolated state/traces/outputs folders, grade it with eval.grader_command, and sum its usd."""
    eval_cfg = config().get("eval") or {}
    command, grader_command = eval_cfg.get("command") or "", eval_cfg.get("grader_command") or ""
    max_usd = eval_cfg.get("max_usd")
    out_root = ROOT / "build" / "evals"
    recs = []
    for c in cases:
        started = time.time()
        spec = {k: val for k, val in c.items() if not k.startswith("_")}
        f = c["_file"]
        rec = {"pack": v["name"], "name": spec.get("name") or f.stem, "kind": "golden", "file": rel(f),
               "covers": spec.get("covers") or [], "failure_path": bool(spec.get("failure")), "result": "skipped",
               "first_failure": None, "seconds": 0.0, "usd": None, "owner": v["name"], "finding": None,
               "regression": False}
        try:
            mode = resolve_mode(spec["envelope"]["mode"], check_visibility=False)
        except PmosError as e:
            rec.update(result="error", first_failure=str(e))
            recs.append(rec)
            continue
        man = mode["manifest"]
        folder = man["name"].replace("/", "__") if c["_where"] == "golden" else f"{v['name']}__workflows"
        case_dir = out_root / folder / f.stem
        shutil.rmtree(case_dir, ignore_errors=True)   # every run starts from empty state, traces, outputs
        case_dir.mkdir(parents=True, exist_ok=True)
        state["rendered"] += 1
        role = resolve_role(man["default_role"], mode["pack"])
        prompt, _ = golden_prompt(spec, man, role, case_dir, spec.get("name", f.stem))
        grader = golden_grader(spec, mode, role, case_dir, spec.get("name", f.stem))
        (case_dir / "prompt.md").write_text("\n".join(prompt), encoding="utf-8")
        (case_dir / "grader.md").write_text("\n".join(grader) + "\n", encoding="utf-8")
        if not command:
            rec["first_failure"] = "rendered only: set eval.command in pm-os.yaml to run it"
            recs.append(rec)
            continue
        if max_usd is not None and state["usd"] >= float(max_usd):
            rec["first_failure"] = f"not run: this run's golden cases already spent ${state['usd']:g} (eval.max_usd ${max_usd:g})"
            recs.append(rec)
            continue
        env_vars = {**os.environ,
                    "PMOS_STATE_DIR": str(case_dir / "state"),
                    "PMOS_TRACES_DIR": str(case_dir / "traces"),
                    "PMOS_OUTPUTS_DIR": str(case_dir / "outputs"),
                    "PMOS_TASK_SEQ_START": str(state["rendered"] * 100 + 1)}   # task ids distinct across cases
        cmd = command.replace("{prompt_file}", str(case_dir / "prompt.md"))
        proc = subprocess.run(cmd, shell=True, cwd=ROOT, env=env_vars, capture_output=True, text=True, timeout=1800)
        (case_dir / "output.md").write_text(proc.stdout + ("\n\n[stderr]\n" + proc.stderr if proc.stderr else ""),
                                            encoding="utf-8")
        usd = 0.0
        for tf in (case_dir / "state" / "tasks").glob("T-*.json"):
            try:
                usd += usd_spent(load_json(tf))
            except (json.JSONDecodeError, ValueError, TypeError):
                pass
        state["usd"] += usd
        rec["usd"] = round(usd, 4)
        line = f"ran {man['name']}/{f.stem}: exit {proc.returncode}"
        if grader_command:
            score = grade_case(grader_command, case_dir, env_vars)
            state["scores"].append({"case": f"{man['name']}/{f.stem}", "passed": score["passed"]})
            failing = [ln.get("line") for ln in score.get("lines") or [] if isinstance(ln, dict) and not ln.get("pass")]
            rec.update(result="pass" if score["passed"] else "fail",
                       first_failure=None if score["passed"] else (score.get("error") or (failing or ["grader: failed"])[0]))
            line += f", graded {'pass' if score['passed'] else 'FAIL'}"
        else:
            rec.update(result="pass" if proc.returncode == 0 else "fail",
                       first_failure=None if proc.returncode == 0 else f"eval.command exited {proc.returncode}")
        rec["seconds"] = round(time.time() - started, 2)
        log(line)
        recs.append(rec)
    return recs


def counts(recs: list[dict]) -> dict:
    out = {"cases": len(recs), "passed": sum(r["result"] == "pass" for r in recs),
           "failed": sum(r["result"] in ("fail", "error") for r in recs),
           "skipped": sum(r["result"] == "skipped" for r in recs),
           "seconds": round(sum(r["seconds"] for r in recs), 2),
           "usd": round(sum(r["usd"] or 0 for r in recs), 4)}
    return out


def eval_summary_line(pack: str, recs: list[dict]) -> str:
    """`<pack>: P/N passed[, F failed][, S skipped] (conformance a/b, golden c/d)` over the cases that ran."""
    if not recs:
        return f"{pack}: no cases"
    c = counts(recs)
    ran = c["cases"] - c["skipped"]
    kinds = []
    for k in ("conformance", "golden"):
        kc = counts([r for r in recs if r["kind"] == k])
        if kc["cases"] - kc["skipped"]:
            kinds.append(f"{k} {kc['passed']}/{kc['cases'] - kc['skipped']}")
    if not ran:
        return f"{pack}: {c['skipped']} golden case(s) rendered, not run (set eval.command to run them)"
    return (f"{pack}: {c['passed']}/{ran} passed" + (f", {c['failed']} failed" if c["failed"] else "")
            + (f", {c['skipped']} skipped" if c["skipped"] else "") + f" ({', '.join(kinds)})"
            + (f", ${c['usd']:g}" if c["usd"] else ""))


def eval_table(recs: list[dict]) -> str:
    rows = [("case", "kind", "result", "covers", "first failing expectation")]
    for r in recs:
        res = r["result"].upper() + (" (failure path)" if r["failure_path"] and r["result"] == "pass" else "")
        rows.append((r["name"], r["kind"], res, ", ".join(r["covers"])[:48], (r["first_failure"] or "")[:100]))
    widths = [min(max(len(str(row[i])) for row in rows), cap) for i, cap in enumerate((40, 11, 22, 48, 100))]
    lines = []
    for j, row in enumerate(rows):
        lines.append("  ".join(str(cell)[:w].ljust(w) for cell, w in zip(row, widths)).rstrip())
        if j == 0:
            lines.append("  ".join("-" * w for w in widths))
    return "\n".join(lines)


def eval_targets(args) -> list[tuple[str, str | None]]:
    """[(pack, mode or None)] for `pmos eval`: --all or no target = core + every installed pack."""
    if args.all or not args.targets:
        return [(CORE, None)] + [(e["name"], None) for e in install_list() if e["name"] in packs()]
    out = []
    for t in args.targets:
        if t in packs():
            out.append((t, None))
        elif "/" in t and t.split("/")[0] in packs() and any(m["manifest"].get("name") == t for m in discover_modes()):
            out.append((t.split("/")[0], t))
        else:
            raise PmosError(f"'{t}' is not core, an installed pack or one of its modes (`pmos pack list`)")
    return out


def cmd_eval_coverage(args) -> int:
    views = []
    for t in args.targets or []:
        if (Path(t) / "pack.yaml").exists():
            views.append(pack_view(d=Path(t)))
        elif t in packs():
            views.append(pack_view(t))
        else:
            raise PmosError(f"'{t}' is not core, an installed pack or a pack folder")
    if not views:
        views = [pack_view(n) for n, _ in eval_targets(argparse.Namespace(all=True, targets=[]))]
    total = 0
    for v in views:
        cases, errors = load_view_cases(v)
        rows, gaps = coverage(v, cases)
        print(f"## {v['name']} ({rel(v['dir'])})")
        for ref, need, names in rows:
            shown = ", ".join(names[:4]) + (f" (+{len(names) - 4})" if len(names) > 4 else "")
            print(f"- {ref}  [{need}]  {shown or 'NO CASE'}")
        problems = errors + gaps
        total += len(problems)
        if problems:
            print(f"{v['name']} gaps: {len(problems)}")
            print("\n".join(f"  - {p}" for p in problems))
        else:
            print(f"{v['name']}: no gaps")
        print()
    print("coverage: no gaps" if not total else f"coverage: {total} gap(s) or case error(s)")
    return 1 if total else 0


def eval_estimate(n_conf: int, n_gold: int) -> str:
    """`estimate: …` — cases × typical seconds (the mean from the last build/evals/results.json, else
    eval.typical_seconds), and whether that is over cos.inline_max_seconds, so the CoS can background it."""
    typical = {"conformance": 3.0, "golden": 300.0, **((config().get("eval") or {}).get("typical_seconds") or {})}
    try:
        last = load_json(ROOT / "build" / "evals" / "results.json")["cases"]
        for kind in typical:
            secs = [c["seconds"] for c in last if c.get("kind") == kind and c.get("result") in ("pass", "fail")]
            if secs:
                typical[kind] = sum(secs) / len(secs)
    except (OSError, ValueError, KeyError, TypeError):
        pass
    golden_runs = bool((config().get("eval") or {}).get("command"))
    t_conf, t_gold = float(typical["conformance"]), float(typical["golden"]) if golden_runs else 0.0
    jobs = min(8, os.cpu_count() or 2)
    wall = math.ceil(n_conf / jobs) * t_conf + n_gold * t_gold
    parts = [f"{n_conf} conformance × ~{round(t_conf, 1):g} s"] if n_conf else []
    parts += [f"{n_gold} golden × ~{round(t_gold, 1):g} s"] if n_gold else []
    shown = f"{round(wall):d} s" if wall < 120 else f"{wall / 60:.0f} min"
    limit = (config().get("cos") or {}).get("inline_max_seconds", 10)
    verdict = (f"over cos.inline_max_seconds ({limit} s): run it in the background" if wall > limit
               else f"within cos.inline_max_seconds ({limit} s)")
    return (f"estimate: {n_conf + n_gold} case(s) ({', '.join(parts) or 'none'}) ≈ {shown}; {verdict}"
            + ("" if golden_runs or not n_gold else "; golden cases only render (no eval.command)"))


def cmd_eval(args) -> int:
    if args.framework:  # alias of `pmos eval core --kind conformance`, with review filters and the legacy table
        fe = framework_eval_module()
        groups = [g for g in args.targets if g in fe.REVIEWS] or fe.REVIEWS
        n = len(fe.load_cases(CORE_CASES, groups, args.case))
        print(eval_estimate(n, 0), file=sys.stderr if args.json else sys.stdout, flush=True)
        return fe.run(args.targets, case=args.case, as_json=args.json)
    if args.coverage:
        return cmd_eval_coverage(args)
    kind = args.kind or "all"
    log = (lambda m: print(m, file=sys.stderr)) if args.json else print
    targets = eval_targets(args)
    plan = []   # (view, conformance cases, golden cases)
    for pack, mode in targets:
        v = pack_view(pack)
        cases, errors = load_view_cases(v)
        if errors:
            raise PmosError(f"{pack}: fix these eval cases first:\n  - " + "\n  - ".join(errors))
        if args.case:
            cases = [c for c in cases if fnmatch.fnmatch(str(c.get("name") or ""), args.case)]
        conf = [c for c in cases if c.get("kind") == "conformance"]
        gold = [c for c in cases if c.get("kind") == "golden"]
        if mode:
            local = mode.split("/", 1)[1]
            std = mode_standard(next(m["manifest"] for m in v["modes"] if m["name"] == mode), pack)
            std_ref = "standard:" + std["ref"].replace(":standards/", ":") if std else None
            conf = [c for c in conf if any(r in (f"mode:{mode}", std_ref) or r.startswith(f"script:modes/{local}/")
                                           for r in c.get("covers") or [])]
            gold = [c for c in gold if c["_mode"] == mode]
        plan.append((v, conf if kind in ("conformance", "all") else [], gold if kind in ("golden", "all") else []))
    print(eval_estimate(sum(len(c) for _, c, _ in plan), sum(len(g) for _, _, g in plan)),
          file=sys.stderr if args.json else sys.stdout, flush=True)
    results: dict[str, list[dict]] = {v["name"]: [] for v, _, _ in plan}
    for v, conf, _ in plan:                      # conformance first: cheap, and no model
        results[v["name"]] += [case_record(r) for r in run_conformance(v, conf)]
    state = {"rendered": 0, "usd": 0.0, "scores": []}
    for v, _, gold in plan:
        results[v["name"]] += run_golden(v, gold, state, log)
    out_root = ROOT / "build" / "evals"
    if state["scores"]:
        passed = sum(1 for sc in state["scores"] if sc["passed"])
        write_json(out_root / "summary.json", {"cases": len(state["scores"]), "passed": passed,
                                               "pass_rate": round(passed / len(state["scores"]), 3),
                                               "results": state["scores"]})
    all_recs = [r for recs in results.values() for r in recs]

    def with_kinds(recs):
        c = counts(recs)
        c["kinds"] = {k: counts([r for r in recs if r["kind"] == k]) for k in ("conformance", "golden")
                      if any(r["kind"] == k for r in recs)}
        return c
    report = {"contract": "eval-result@1", "generated_at": now(), "runner": "pmos", "kind": kind,
              "targets": [m or p for p, m in targets], "packs": {p: with_kinds(r) for p, r in results.items()},
              "totals": with_kinds(all_recs), "cases": all_recs}
    validate_against(report, "eval-result", "eval result")
    write_json(out_root / "results.json", report)
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        for pack, recs in results.items():
            if recs:
                print(f"\n== {pack} ==")
                print(eval_table(recs))
        print()
        for pack, recs in results.items():
            print(eval_summary_line(pack, recs))
        t = report["totals"]
        print(f"total: {t['passed']} passed, {t['failed']} failed, {t['skipped']} skipped"
              + (f", ${t['usd']:g} spent on golden runs" if t["usd"] else "") + f" -> {rel(out_root / 'results.json')}")
        if t["skipped"] and not (config().get("eval") or {}).get("command"):
            print(f"golden cases rendered to {rel(out_root)}; set eval.command in pm-os.yaml to run them "
                  f"(budget: eval.max_usd ${(config().get('eval') or {}).get('max_usd', 0):g} per run)")
    return 1 if report["totals"]["failed"] else 0


def admission_evals(name: str, d: Path, man: dict, with_golden: bool) -> list[str]:
    """Run a candidate pack's conformance cases (and, with --with-golden, its golden cases) in a sandbox.
    Prints the counts; returns the failures (empty = admitted)."""
    v = pack_view(d=d)
    cases, _ = load_view_cases(v)
    conf = [c for c in cases if c.get("kind") == "conformance"]
    failures = []
    if conf:
        recs = run_conformance(v, conf, candidate=d)
        bad = [r for r in recs if r["result"] not in ("pass", "skipped")]
        held = ["core"] + ([] if name == config().get("cos_pack") else ["the CoS pack"]) + list(man.get("depends") or [])
        print(f"conformance: {len(recs) - len(bad)}/{len(recs)} case(s) passed in a sandbox ({', '.join(held)} "
              f"and {name})")
        failures += [f"conformance case {r['name']} failed: {r['failure']}" for r in bad]
    if with_golden and [c for c in cases if c.get("kind") == "golden"]:
        copy, _rel = eval_sandbox(name, d, man)
        try:
            proc = subprocess.run([sys.executable, "scripts/pmos.py", "eval", name, "--kind", "golden", "--json"],
                                  cwd=copy, capture_output=True, text=True, env=clean_env(), timeout=7200)
            try:
                rep = json.loads(proc.stdout)
            except json.JSONDecodeError:
                raise PmosError(f"golden run in the sandbox failed:\n{proc.stdout[-1500:]}{proc.stderr[-1500:]}")
        finally:
            shutil.rmtree(copy.parent, ignore_errors=True)
        t = rep["totals"]
        print(f"golden: {t['passed']}/{t['cases']} case(s) passed in the sandbox (eval.command)"
              + (f", ${t['usd']:g}" if t.get("usd") else ""))
        failures += [f"golden case {c['name']} {c['result']}: {c['first_failure']}" for c in rep["cases"]
                     if c["result"] != "pass"]
    return failures


def grade_case(grader_command: str, case_dir: Path, env_vars: dict) -> dict:
    """Run eval.grader_command on one case; its stdout JSON becomes score.json."""
    cmd = (grader_command.replace("{grader_file}", str(case_dir / "grader.md"))
           .replace("{output_file}", str(case_dir / "output.md")))
    proc = subprocess.run(cmd, shell=True, cwd=ROOT, env=env_vars, capture_output=True, text=True, timeout=1800)
    text = proc.stdout.strip()
    m = re.search(r"\{.*\}", text, flags=re.S)   # tolerate prose or code fences around the JSON
    try:
        score = json.loads(m.group(0) if m else text)
        if not isinstance(score, dict) or not isinstance(score.get("passed"), bool):
            raise ValueError('needs a boolean "passed"')
    except (ValueError, json.JSONDecodeError) as e:
        score = {"passed": False, "error": f"grader output is not the expected JSON: {e}",
                 "exit": proc.returncode, "stdout": text[-2000:], "stderr": proc.stderr[-2000:]}
    write_json(case_dir / "score.json", score)
    return score


# --------------------------------------------------------------------------- cli
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="pmos", description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("validate", help="check core, every installed pack and their references").set_defaults(
        fn=cmd_validate)
    sub.add_parser("board", help="regenerate state/status.md").set_defaults(fn=cmd_board)

    pth = sub.add_parser("path", help="print a configured path (outputs, state, traces, context, ...), with the "
                                      "PMOS_*_DIR overrides applied; for pack scripts")
    pth.add_argument("name", help="a key of `paths` in pm-os.yaml, e.g. outputs")
    pth.set_defaults(fn=cmd_path)

    c = sub.add_parser("catalog", help="write state/catalog.md and AGENTS.md")
    c.add_argument("--pack", help="print this pack's modes (with internal ones) and what each accepts")
    c.set_defaults(fn=cmd_catalog)

    d = sub.add_parser("decide", help="append a decision to context/decisions.log")
    d.add_argument("text", help="what was decided, and why")
    d.add_argument("--by", default="cos", help="who decided (default: cos)")
    d.set_defaults(fn=cmd_decide)

    st = sub.add_parser("stats", help="cost, run time, first-pass review rate and revise-after-approval rate, per "
                                      "mode and per effort level, from the traces")
    st.add_argument("--mode", help="only this mode (pack/mode)")
    st.add_argument("--json", action="store_true", help="print JSON instead of a table")
    st.set_defaults(fn=cmd_stats)

    li = sub.add_parser("lint", help="check component text is tight: word budgets per kind, mode step structure, "
                                     "filler phrases, principles cited not copied, no duplicate paragraphs")
    li.add_argument("targets", nargs="*", help="core, installed pack names or pack folders (a staged pack); "
                                               "empty = core and every installed pack")
    li.add_argument("--json", action="store_true", help="print the report as JSON (lint@1)")
    li.set_defaults(fn=cmd_lint)

    ct = sub.add_parser("cos-turn", help="log one Chief of Staff reply to the traces (time to reply, tool calls); "
                                         "`pmos stats` reports them")
    ct.add_argument("--started", required=True, help="when the PM's message arrived (ISO 8601)")
    ct.add_argument("--replied", help="when the CoS replied (ISO 8601; default: now)")
    ct.add_argument("--tool-calls", type=int, required=True, dest="tool_calls",
                    help="tool calls the CoS made before replying (not counting this one)")
    ct.add_argument("--note", help="optional: what the turn was, e.g. 'status question'")
    ct.set_defaults(fn=cmd_cos_turn)

    r = sub.add_parser("render", help="generate harness config from the installed packs")
    r.add_argument("adapter", choices=["agents-md", "claude-code", "generic"], help="which harness to generate for")
    r.set_defaults(fn=cmd_render)

    e = sub.add_parser("eval", help="run eval@1 cases: conformance (code) then golden (model) per pack")
    e.add_argument("targets", nargs="*", help="core, pack names or pack/mode names (with --framework: core's groups; "
                                              "with --coverage: also pack folders); empty = --all")
    e.add_argument("--all", action="store_true", help="core and every installed pack")
    e.add_argument("--kind", choices=["conformance", "golden", "all"],
                   help="which cases to run (default: all; golden cases run only when eval.command is set)")
    e.add_argument("--json", action="store_true", help="print eval-result@1 JSON (also written to build/evals/results.json)")
    e.add_argument("--coverage", action="store_true",
                   help="list each pack's features and the cases covering them; exit 1 on any gap")
    e.add_argument("--case", help="only cases whose name matches this glob")
    e.add_argument("--framework", action="store_true",
                   help="alias for `eval core --kind conformance`: core's cases with the framework table")
    e.set_defaults(fn=cmd_eval)

    pk = sub.add_parser("pack", help="install, upgrade, list or remove packs").add_subparsers(
        dest="pack_cmd", required=True)
    pk.add_parser("list", help="installed packs and their approved grants").set_defaults(fn=cmd_pack_list)
    pa = pk.add_parser("add", help="admit and install (or upgrade) a pack")
    pa.add_argument("path", help="the pack folder (contains pack.yaml)")
    pa.add_argument("--source", default="local", choices=["local", "org", "third-party"],
                    help="where the pack comes from; breaks ties between packs (local first)")
    pa.add_argument("--approve-grants", action="store_true",
                    help="approve the grants the pack requests (needed for new or wider grants)")
    pa.add_argument("--upgrade", action="store_true",
                    help="replace an installed pack; its version must be higher than the installed one")
    pa.add_argument("--dry-run", action="store_true", help="run admission and show grants without installing")
    pa.add_argument("--with-golden", action="store_true",
                    help="also run the pack's golden cases in the sandbox, through eval.command (costs money)")
    pa.add_argument("--force", action="store_true",
                    help="with --upgrade: install even if packs that depend on this one would fail their checks")
    pa.set_defaults(fn=cmd_pack_add)
    pr = pk.add_parser("remove", help="uninstall a pack (refused while others depend on it or it has open tasks)")
    pr.add_argument("name", help="the pack name")
    pr.set_defaults(fn=cmd_pack_remove)
    pp = pk.add_parser("path", help="print an installed pack's directory, for pack scripts")
    pp.add_argument("name", help="the pack's name")
    pp.set_defaults(fn=cmd_pack_path)

    ro = sub.add_parser("role", help="inspect roles").add_subparsers(dest="role_cmd", required=True)
    rs_ = ro.add_parser("show", help="print a role's persona, skills, principles, context and rubric")
    rs_.add_argument("role", help="PACK/ROLE, e.g. pm/doc-writer")
    rs_.set_defaults(fn=cmd_role_show)

    t = sub.add_parser("task", help="create tasks and move them through their states").add_subparsers(
        dest="task_cmd", required=True)
    n = t.add_parser("new", help="create a task envelope (queued)")
    n.add_argument("--mode", required=True, help="PACK/MODE, optionally pinned: pm/prd or pm/prd@^0.2")
    n.add_argument("--verb", choices=["plan", "draft", "analyze", "execute", "review"],
                   help="one of the mode's verbs; optional when the mode declares only one")
    n.add_argument("--inputs", required=True, help="JSON object, or @path/to/inputs.json")
    n.add_argument("--role", help="run under this role instead of the mode's default_role")
    n.add_argument("--workflow", help="which of the mode's named workflows to run, for modes that declare "
                                         "several (recorded in the envelope for the durable runtime)")
    n.add_argument("--risk", choices=["low", "medium", "high"], help="default: the mode's risk")
    n.add_argument("--effort", choices=EFFORT_LEVELS,
                   help="how hard the model reasons; default: mode > role > agent > defaults.effort, risk-scaled")
    n.add_argument("--dispatch", choices=DISPATCH_VALUES,
                   help="how the CoS runs the subagent; default: mode > role > agent > defaults.dispatch")
    n.add_argument("--approval", choices=["none", "before_publish", "before_execute"],
                   help="when the PM must approve; default: the mode's approval")
    n.add_argument("--acceptance", action="append", help="an extra must line for this task (task-1, …; repeatable)")
    n.add_argument("--depends-on", action="append", dest="depends_on", help="a task id that must finish first (repeatable)")
    n.add_argument("--parent", help="the task creating this one as its child")
    n.add_argument("--budget-usd", type=float, help="spending cap in USD; default from pm-os.yaml")
    n.add_argument("--budget-minutes", type=float, help="time cap in minutes; default from pm-os.yaml")
    n.add_argument("--reply-to", default="cos", help="who gets the result (default: cos)")
    n.add_argument("--by", default="cos", help="who creates the task, for the trace (default: cos)")
    n.add_argument("--note", help="a note for the task history")
    n.add_argument("--instructions", help="the PM's own instructions, verbatim; the Worker follows them")
    n.add_argument("--origin", help="where the task came from, as PACK:REF, e.g. cos:td-12 (a todo)")
    n.add_argument("--product", help="the product this task is for: adds the pack's overlay skills for it "
                                     "(pack.yaml overlays); default: the parent's, else product: in context/product.md")
    n.set_defaults(fn=cmd_task_new)

    s = t.add_parser("show", help="print a task's brief: mode, role, principles, then envelope, history")
    s.add_argument("id", help="task id")
    s.add_argument("--for-review", action="store_true", help="add the result and the review checklist")
    s.add_argument("--checklist", action="store_true",
                   help="print the review checklist as JSON: [{id, kind, group, text, ...}] (kind core|must|code|should; "
                        "code lines carry settled), the ids `task review --verdicts` takes")
    s.add_argument("--json", action="store_true", help="print the task state as JSON")
    s.set_defaults(fn=cmd_task_show)

    mv = t.add_parser("move", help="change a task's state (legal transitions only)")
    mv.add_argument("id", help="task id")
    mv.add_argument("state", choices=sorted(TRANSITIONS), help="the new state")
    mv.add_argument("--note", help="why, for the task history (e.g. the PM's answer)")
    mv.add_argument("--by", default="agent", help="who moves it, for the trace (default: agent)")
    mv.set_defaults(fn=cmd_task_move)

    rs = t.add_parser("result", help="submit a Worker result (validated against contracts/result.schema.json)")
    rs.add_argument("id", help="task id")
    rs.add_argument("file", help="the result JSON, usually outputs/<id>/result.json")
    rs.add_argument("--by", default="worker", help="who submits it, for the trace (default: worker)")
    rs.set_defaults(fn=cmd_task_result)

    rv = t.add_parser("review", help="record the Reviewer's per-line verdicts; pmos computes pass or fail")
    rv.add_argument("id", help="task id")
    rv.add_argument("--verdicts", help='JSON file (or - for stdin): {"lines": [{"id": <checklist id>, "pass": true|false, '
                                       '"evidence": <where in the artifact>, "fix": <what must change, if failed>}]}, one per '
                                       'line that is not settled; pmos computes the score and the pass')
    rv.add_argument("--passed", help="ignored (pmos computes the pass from --verdicts); kept so old calls get a clear error")
    rv.add_argument("--score", type=float, help="ignored; pmos computes the score from the should lines")
    rv.add_argument("--note", action="append", help="a review note: what is missing and where (repeatable)")
    rv.add_argument("--by", default="reviewer", help="who reviewed, for the trace (default: reviewer)")
    rv.set_defaults(fn=cmd_task_review)

    ap = t.add_parser("approve", help="record the PM's approval of an awaiting_approval task")
    ap.add_argument("id", help="task id")
    ap.add_argument("--by", required=True, help="who approved (the PM)")
    ap.add_argument("--note", help="a note for the task history")
    ap.set_defaults(fn=cmd_task_approve)

    ls = t.add_parser("list", help="list open tasks")
    ls.add_argument("--state", choices=sorted(TRANSITIONS), help="only tasks in this state")
    ls.add_argument("--all", action="store_true", help="include done and failed tasks")
    ls.set_defaults(fn=cmd_task_list)

    st = t.add_parser("state", help="print a task's state (the full task state JSON with --json), for scripts")
    st.add_argument("id", help="the task id")
    st.add_argument("--json", action="store_true", help="print the full task state as JSON")
    st.set_defaults(fn=cmd_task_state)

    ac = sub.add_parser("action", help="run an approved task's actions (the Operator)").add_subparsers(dest="action_cmd", required=True)
    ar = ac.add_parser("run", help="run an approved task's actions through its pack's handlers")
    ar.add_argument("id", help="the approved task")
    ar.add_argument("--key", help="run only the action with this idempotency_key")
    ar.add_argument("--by", default="operator", help="who runs them (recorded in history)")
    ar.add_argument("--receipt", action="append", default=[], metavar="KEY=RECEIPT",
                    help="the id the external tool returned for an external action; marks it sent (repeatable)")
    ar.set_defaults(fn=cmd_action_run)

    chn = sub.add_parser("channel", help="the channel registry: show channels, check a text against one, render it").add_subparsers(
        dest="channel_cmd", required=True)
    cs = chn.add_parser("show", help="a channel's format, limits, recipient and send handler (no REF: list them)")
    cs.add_argument("ref", nargs="?", help="pack:channel/name, or channel/name with --from")
    cs.add_argument("--from", dest="from_pack", help="the calling pack: its depends and exports decide what it sees")
    cs.add_argument("--json", action="store_true", help="print the channel as JSON (the fields cos/notify reads)")
    cs.set_defaults(fn=cmd_channel_show)
    cc = chn.add_parser("check", help="check a text's limits and a recipient against a channel")
    cc.add_argument("ref")
    cc.add_argument("--text", required=True, help="a file, or - for stdin")
    cc.add_argument("--recipient", help="check this recipient against the channel's pattern")
    cc.add_argument("--from", dest="from_pack", help="the calling pack: its depends and exports decide what it sees")
    cc.set_defaults(fn=cmd_channel_check)
    cr = chn.add_parser("render", help="print a Markdown text in the channel's format")
    cr.add_argument("ref")
    cr.add_argument("--text", required=True, help="a file, or - for stdin")
    cr.add_argument("--from", dest="from_pack", help="the calling pack: its depends and exports decide what it sees")
    cr.set_defaults(fn=cmd_channel_render)
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

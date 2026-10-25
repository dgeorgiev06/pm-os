#!/usr/bin/env python3
"""pmos — the deterministic core of pm-os. Harness- and model-neutral.

Every state change goes through this CLI, so any agent harness (or a human) can drive the
framework the same way. Later, the same functions become steps in a durable workflow engine.

  pmos validate                         check core, every installed pack, and their references
  pmos pack list                        installed packs
  pmos pack add PATH [--source S] [--approve-grants] [--upgrade] [--dry-run]
  pmos pack remove NAME
  pmos catalog [--pack NAME]            write state/catalog.md + AGENTS.md; --pack prints one pack's modes
  pmos role show PACK/ROLE              a role's persona, skills, principles, context, rubric
  pmos task new --mode PACK/MODE --verb V --inputs JSON [--instructions TEXT] [--todo td-N] [...]
  pmos task show ID [--for-review] [--json]
  pmos task move ID STATE [--note TEXT] [--by WHO]
  pmos task result ID RESULT.json
  pmos task review ID --passed true|false [--score N] [--note TEXT ...]
  pmos task approve ID --by WHO [--note TEXT]
  pmos task list [--state STATE] [--all]
  pmos board                            regenerate state/status.md
  pmos decide "TEXT" [--by WHO]         append to context/decisions.log
  pmos render agents-md|claude-code|generic
  pmos eval [PACK | PACK/MODE ...]      render (and optionally run) golden tasks

Naming: modes are <pack>/<mode>; roles <pack>/<role>; skills and principles <pack>:<path>.
Inside a pack, a bare name means "this pack". Core resources belong to the pack "core".
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
CORE = "core"
TERMINAL = {"done", "failed"}
OPEN_STATES = ["queued", "running", "waiting", "in_review", "revise",
               "awaiting_approval", "approved", "blocked"]
GRANT_LEVEL = {"read": 1, "draft": 2, "write": 3}

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


# --------------------------------------------------------------------------- config
_CACHE: dict = {}


def clear_cache() -> None:
    _CACHE.clear()


def config() -> dict:
    if "config" not in _CACHE:
        _CACHE["config"] = load_yaml(ROOT / "pm-os.yaml")
    return _CACHE["config"]


def path_of(key: str) -> Path:
    overrides = {"state": "PMOS_STATE_DIR", "traces": "PMOS_TRACES_DIR"}
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
    return local in (exports.get(kind) or [])


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
        if meta.get("name") != expected:
            errors.append(f"{rel(path)}: frontmatter name should be '{expected}' (got {meta.get('name')!r})")
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
            sid = q_skill(s, name)
            if sid not in skills:
                errors.append(f"role {fq}: skill '{sid}' not found")
            else:
                err = visibility_error(name, sid.split(":")[0], "skills", sid.split(":", 1)[1])
                if err:
                    errors.append(f"role {fq}: {err}")
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
        for key in ("name", "description", "tier", "grants"):
            if key not in meta:
                errors.append(f"{rel(path)}: frontmatter missing '{key}'")
        if meta.get("tier") not in ("small", "mid", "top"):
            errors.append(f"{rel(path)}: tier must be small, mid or top")

    # modes
    mode_names = set()
    for m in [m for m in discover_modes() if m["pack"] == name]:
        mm, where = m["manifest"], rel(m["path"])
        errs = schema_errors(mm, "mode", where)
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
            if meta.get("name") != render_name(mm["name"]):
                errors.append(f"{rel(skill_path)}: frontmatter name should be '{render_name(mm['name'])}'")
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
        for call in mm.get("calls", []):
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
        for mname in exports.get("modes", []) or []:
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
        router = man.get("router")
        if router and router not in (exports.get("modes") or []):
            errors.append(f"{where_pack}: router '{router}' must be an exported mode")
    return errors, warnings


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
    cos = config().get("cos_pack")
    if cos not in packs():
        errors.append(f"pm-os.yaml: cos_pack '{cos}' is not installed")
    elif not packs()[cos]["manifest"].get("cos"):
        errors.append(f"pm-os.yaml: cos_pack '{cos}' doesn't supply a Chief of Staff (no 'cos' in pack.yaml)")
    else:
        agents_md = ROOT / "AGENTS.md"
        if not agents_md.exists() or agents_md.read_text(encoding="utf-8") != build_agents_md():
            warnings.append("AGENTS.md is out of date; run `pmos catalog` (or `pmos render agents-md`)")
    return errors, warnings


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
          f"{len(all_principles())} principle(s), {len(all_agents())} agent(s).")
    return 0


# --------------------------------------------------------------------------- packs CLI
def mode_grants(pack: str) -> dict[str, str]:
    union: dict[str, str] = {}
    for m in discover_modes():
        if m["pack"] != pack:
            continue
        for system, level in (m["manifest"].get("grants") or {}).items():
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

    stored_path = rel(d) if str(d).startswith(str(ROOT)) else str(d)
    entry = {"name": name, "version": man["version"], "path": stored_path, "source": args.source,
             "enabled": True, "grants_approved": {}, "installed_at": now()}
    trial = [e for e in entries if e["name"] != name] + [entry]
    _CACHE["install"] = trial
    _CACHE.pop("packs", None)
    for k in ("skills", "roles", "modes"):
        _CACHE.pop(k, None)
    errors, warnings = check_pack(name, check_grants=False)
    for w in warnings:
        print(f"warn: {w}")
    if errors:
        clear_cache()
        print(f"Admission failed for pack '{name}':")
        for e in errors:
            print(f"  - {e}")
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
    write_catalog()
    print(f"{'upgraded' if existing else 'installed'} {name} {man['version']} from {stored_path} "
          f"({len([m for m in discover_modes() if m['pack'] == name])} mode(s)); catalog and AGENTS.md updated")
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


def build_agents_md() -> str:
    cos = packs()[config()["cos_pack"]]
    manual = (cos["dir"] / cos["manifest"]["cos"]).read_text(encoding="utf-8").rstrip()
    return ("<!-- Generated by `pmos` from " + rel(cos["dir"] / cos["manifest"]["cos"]) +
            " and packs.yaml. Edit those, then run `pmos catalog`. -->\n\n" + manual +
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


def role_lines(role: dict) -> list[str]:
    owner, skills, principles = role["_pack"], all_skills(), all_principles()
    ctx = ROOT / config()["paths"]["context"]
    out = [f"## Role: {owner}/{role['_name']} (agent: {role['agent']}, tier: {role['tier']})",
           f"- persona: {role['persona']}"]
    for s in role.get("skills", []):
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
        "ts": now(), "event": event, "task_id": env["id"], "mode": env["mode"], "pack": task.get("pack"),
        "mode_version": task.get("mode_version"), "role": task.get("role"),
        "parent": env.get("parent"), "todo": task.get("todo"), **fields,
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
    parent = load_task(args.parent) if args.parent else None
    from_pack = parent.get("pack") if parent else None     # None = the CoS: exported modes only
    mode = resolve_mode(args.mode, from_pack=from_pack)
    man, pack = mode["manifest"], mode["pack"]
    if grant_excess(mode):
        raise PmosError(grant_excess_message(mode))
    inputs = parse_inputs(args.inputs)
    check_inputs(inputs, man.get("accepts", {}), man["name"])
    if man.get("verbs") and args.verb not in man["verbs"]:
        raise PmosError(f"{man['name']} supports verbs {man['verbs']}, not '{args.verb}'")
    role = resolve_role(args.role or man["default_role"], pack)
    role_fq = f"{role['_pack']}/{role['_name']}"

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
    if args.instructions:
        envelope["instructions"] = args.instructions
    if args.todo:
        envelope["origin"] = {"todo": args.todo}
    validate_against(envelope, "task", "envelope")
    for dep in envelope["depends_on"]:
        load_task(dep)

    task = {
        "envelope": envelope,
        "state": "queued",
        "pack": pack,
        "todo": args.todo,
        "mode_name": man["name"],
        "mode_version": man["version"],
        "mode_dir": rel(mode["dir"]),
        "role": role_fq,
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


def deps_pending(task: dict) -> list[str]:
    return [d for d in task["envelope"].get("depends_on", []) if load_task(d)["state"] != "done"]


def cmd_task_show(args) -> int:
    task = load_task(args.id)
    if args.json:
        print(json.dumps(task, indent=2, ensure_ascii=False))
        return 0
    env = task["envelope"]
    mode = resolve_mode(f"{task['mode_name']}@{task['mode_version']}", check_visibility=False)
    man = mode["manifest"]
    role = all_roles()[task["role"]]
    out = [
        f"# {env['id']} · {task['mode_name']}@{task['mode_version']} · {env['verb']} · state: {task['state']}",
        "",
        "## Envelope",
        "```json", json.dumps(env, indent=2, ensure_ascii=False), "```",
        "",
    ]
    if env.get("instructions"):
        out += ["## Instructions from the PM (follow these; they come from the PM directly)", "",
                *[f"> {line}" for line in env["instructions"].splitlines()], ""]
    if env.get("origin", {}).get("todo"):
        out += [f"Delegated from todo {env['origin']['todo']}.", ""]
    out += [
        f"## Mode (pack: {task.get('pack')})",
        f"- skill: {rel(mode['dir'] / man.get('skill', 'SKILL.md'))}",
        f"- approval: {env['approval']} · risk: {env['risk']}",
    ]
    if man.get("calls"):
        out.append(f"- may call: {', '.join(man['calls'])}")
    for extra in man.get("roles", []):
        out.append(f"- also uses role: {q_role(extra, mode['pack'])} (`pmos role show {q_role(extra, mode['pack'])}`)")
    out += ["", *role_lines(role)]
    out += ["", "## Principles (read each before you start; the Reviewer scores these checks)"]
    for group, pid, pr in principles_for(mode, role):
        out.append(f"- [{group}] {pid}: {pr['meta']['check']} ({rel(pr['path'])})")
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
        for a in task["result"].get("actions", []):
            out.append(f"- action: {a['system']}.{a['op']} · {a.get('preview', a['idempotency_key'])}")
    if args.for_review:
        out += ["", "## Review checklist",
                "Pass = every core principle holds and the overall score is 4 or more.", ""]
        for group, pid, pr in principles_for(mode, role):
            out.append(f"- [ ] [{group}] {pid}: {pr['meta']['check']}")
        for r in man.get("rubric", []):
            out.append(f"- [ ] [mode rubric] {r}")
        for r in role.get("rubric", []):
            out.append(f"- [ ] [role rubric] {r}")
        if env.get("instructions"):
            out.append("- [ ] [pm instructions] The result follows the PM's instructions above, "
                       "or the self-check says why it couldn't")
        if task.get("result"):
            out += ["", "## Producer self-check"]
            out += [f"- {'met' if s['met'] else 'NOT met'}: {s['criterion']}" + (f" · {s['note']}" if s.get("note") else "")
                    for s in task["result"].get("self_check", [])] or ["- (none recorded)"]
    print("\n".join(out))
    return 0


def cmd_task_move(args) -> int:
    task = load_task(args.id)
    if args.state == "running":
        pending = deps_pending(task)
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
        print(f"{e['id']}  {t['state']:<17} {t['mode_name']:<20} {t['role']:<22} "
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
        lines += ["| Task | Mode | Role | State | From | Updated |", "| --- | --- | --- | --- | --- | --- |"]
        for t in open_tasks:
            origin = t['envelope'].get('parent') or t.get('todo') or ''
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


# --------------------------------------------------------------------------- render
def all_skill_sources() -> list[tuple[str, Path, Path | None]]:
    """(rendered skill name, SKILL.md path, mode dir or None) for every installed pack."""
    items = [(render_name(sid), path, None) for sid, path in all_skills().items()]
    for m in discover_modes():
        man = m["manifest"]
        items.append((render_name(man["name"]), m["dir"] / man.get("skill", "SKILL.md"), m["dir"]))
    return items


def render_agents_md() -> int:
    write_catalog()
    print("AGENTS.md regenerated from the cos pack")
    return 0


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
        lines += ["---", f"<!-- Generated by `pmos render claude-code` from {rel(src)}. Edit the source, then re-render. -->",
                  "", body.strip(), ""]
        (agents_out / f"{name}.md").write_text("\n".join(lines), encoding="utf-8")
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
        shutil.copy2(skill_md, target / "SKILL.md")
        if mode_dir is not None:
            shutil.copy2(mode_dir / "mode.yaml", target / "mode.yaml")
        names.append(name)
    marker.write_text("\n".join(names) + "\n", encoding="utf-8")

    for w in warnings:
        print(f"warn: {w}")
    print(f"claude-code: {count} agent(s) -> {ad['agents_dir']}, {len(names)} skill(s) -> {ad['skills_dir']}, "
          f"CLAUDE.md -> AGENTS.md")
    return 0


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
        prompt = (ROOT / "AGENTS.md").read_text(encoding="utf-8") if name == "cos" else body.strip() + "\n\n" + "\n".join(skill_index)
        (out / f"{name}.system.md").write_text(prompt + "\n", encoding="utf-8")
        models["agents"][name] = {"tier": meta["tier"], "model": tiers.get(meta["tier"], "")}
        grants[name] = meta.get("grants", [])
    for fq, r in all_roles().items():
        models["roles"][fq] = {"agent": r["agent"], "tier": r["tier"], "model": tiers.get(r["tier"], "")}
    write_json(out / "models.json", models)
    write_json(out / "grants.json", grants)
    shutil.copy2(path_of("state") / "catalog.md", out / "catalog.md")
    print(f"generic: {len(all_agents())} system prompt(s), models.json, grants.json -> {ad['out_dir']}")
    return 0


def cmd_render(args) -> int:
    return {"agents-md": render_agents_md, "claude-code": render_claude_code, "generic": render_generic}[args.adapter]()


# --------------------------------------------------------------------------- eval
def cmd_eval(args) -> int:
    modes = discover_modes()
    if args.targets:
        modes = [m for m in modes if m["pack"] in args.targets or m["manifest"].get("name") in args.targets]
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
            role = resolve_role(man["default_role"], m["pack"])
            grader += ["", "Principles and rubric:"]
            grader += [f"- [ ] [{g}] {pid}: {pr['meta']['check']}" for g, pid, pr in principles_for(m, role)]
            grader += [f"- [ ] {r}" for r in man.get("rubric", [])]
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
    sub.add_parser("board").set_defaults(fn=cmd_board)

    c = sub.add_parser("catalog")
    c.add_argument("--pack")
    c.set_defaults(fn=cmd_catalog)

    d = sub.add_parser("decide")
    d.add_argument("text")
    d.add_argument("--by", default="cos")
    d.set_defaults(fn=cmd_decide)

    r = sub.add_parser("render")
    r.add_argument("adapter", choices=["agents-md", "claude-code", "generic"])
    r.set_defaults(fn=cmd_render)

    e = sub.add_parser("eval")
    e.add_argument("targets", nargs="*", help="pack names or pack/mode names; empty = all")
    e.set_defaults(fn=cmd_eval)

    pk = sub.add_parser("pack").add_subparsers(dest="pack_cmd", required=True)
    pk.add_parser("list").set_defaults(fn=cmd_pack_list)
    pa = pk.add_parser("add")
    pa.add_argument("path")
    pa.add_argument("--source", default="local", choices=["local", "org", "third-party"])
    pa.add_argument("--approve-grants", action="store_true")
    pa.add_argument("--upgrade", action="store_true")
    pa.add_argument("--dry-run", action="store_true", help="run admission and show grants without installing")
    pa.set_defaults(fn=cmd_pack_add)
    pr = pk.add_parser("remove")
    pr.add_argument("name")
    pr.set_defaults(fn=cmd_pack_remove)

    ro = sub.add_parser("role").add_subparsers(dest="role_cmd", required=True)
    rs_ = ro.add_parser("show")
    rs_.add_argument("role")
    rs_.set_defaults(fn=cmd_role_show)

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
    n.add_argument("--instructions", help="the PM's own instructions, verbatim; the Worker follows them")
    n.add_argument("--todo", help="the todo this task was delegated from, e.g. td-12")
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

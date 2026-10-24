"""forge — deterministic helpers for building pm-os modes and packs.

Everything is staged under outputs/<task id>/staged/ first. Nothing touches packs/ until the
Operator runs `apply` for an approved task.

  stage-mode --task ID --pack PACK --name NAME --summary TEXT [--role ROLE] [--into STAGED_PACK_DIR]
      Copy the installed pack to the staging area (or use --into, a pack staged by forge/new-pack),
      add a skeleton mode, export it, and bump the pack's minor version.
  stage-pack --task ID --name NAME --summary TEXT [--role ROLE]
      Create a skeleton pack in the staging area.
  lint DIR [--target packs/NAME]
      Fail on TODO markers and on skill names that don't match their mode (a name is optional). With --target, only the
      files this task added or changed are checked (a new pack's files are all new).
  changes STAGED --target packs/NAME
      JSON list of files added or modified relative to the target.
  apply STAGED --target packs/NAME [--files PATH ...]
      Copy staged files into packs/ (Operator only, after approval).
"""
from __future__ import annotations

import argparse
import filecmp
import json
import re
import shutil
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]

MODE_YAML = """name: {pack}/{name}
version: 0.1.0
contract: task@1
summary: "{summary}"
verbs: [draft]                    # TODO: pick from plan | draft | analyze | execute | review
accepts:
  goal: string                    # TODO: the real inputs; a trailing ? marks optional
returns:
  doc: doc_ref                    # TODO: the real outputs
skill: SKILL.md
default_role: {role}
calls: []                         # modes this one may start as children, version-pinned
grants: {{}}                        # TODO: e.g. {{ jira: read, docs: draft }}
approval: before_publish          # TODO: none | before_publish | before_execute
risk: medium
principles: []                    # cite existing principles before writing new ones
rubric:
  - "TODO: one line a reviewer can check for this mode"
evals: evals/
"""

SKILL_MD = """---
description: "{summary}. Use when a Worker has been given a pm-os task whose envelope mode is {pack}/{name}."
---
# {pack}/{name}

## Steps

1. `[code: python scripts/pmos.py task show <id>]` — load the envelope, role, principles and notes.
2. TODO: the steps, each tagged. Read systems of record fresh; propose external changes as actions.
3. `[model]` Self-check against the envelope's `acceptance` and every principle and rubric line
   `task show` lists.
4. `[code: python scripts/pmos.py task result <id> outputs/<id>/result.json]` — TODO: say what the
   result carries (status, artifacts, actions).
"""

GOLDEN = {
    "name": "TODO: what this case proves",
    "envelope": {"verb": "draft", "mode": "{pack}/{name}", "inputs": {"goal": "TODO"},
                 "acceptance": ["TODO"], "risk": "medium", "approval": "before_publish"},
    "expect": ["TODO: a line a grader can check"],
}

PACK_YAML = """name: {name}
version: 0.1.0
contract: pack@1
summary: "{summary}"
requires:
  core: ^0.2
depends: []                       # other packs this one uses, e.g. [pm@^0.2]
exports:
  modes: []
  roles: [{role}]
  skills: []
  principles: []
"""

ROLES_YAML = """roles:
  {role}:
    agent: worker
    tier: mid                     # small | mid | top
    persona: "TODO: who this role is, in one sentence"
    skills: [core:infra/envelope-io, core:infra/self-check]
    context: []
    principles: []
    rubric: []
"""


def fail(msg: str) -> int:
    print(f"error: {msg}", file=sys.stderr)
    return 1


def installed_pack_dir(pack: str) -> Path:
    data = yaml.safe_load((ROOT / "packs.yaml").read_text(encoding="utf-8")) or {}
    for e in data.get("packs", []):
        if e["name"] == pack:
            return (ROOT / e["path"]).resolve()
    raise SystemExit(f"error: pack '{pack}' is not installed")


def staging(task: str) -> Path:
    return ROOT / "outputs" / task / "staged"


def bump_minor(pack_yaml: Path) -> str:
    text = pack_yaml.read_text(encoding="utf-8")
    m = re.search(r"^version: (\d+)\.(\d+)\.(\d+)", text, flags=re.M)
    new = f"{m.group(1)}.{int(m.group(2)) + 1}.0"
    pack_yaml.write_text(text[:m.start()] + f"version: {new}" + text[m.end():], encoding="utf-8")
    return new


def add_export(pack_yaml: Path, kind: str, item: str) -> None:
    text = pack_yaml.read_text(encoding="utf-8")
    m = re.search(rf"^(\s+{kind}: \[)(.*?)(\])", text, flags=re.M)
    if not m:
        raise SystemExit(f"error: {pack_yaml} has no exports.{kind} list on one line")
    items = [x.strip() for x in m.group(2).split(",") if x.strip()]
    if item not in items:
        items.append(item)
    pack_yaml.write_text(text[:m.start()] + m.group(1) + ", ".join(items) + m.group(3) + text[m.end():],
                         encoding="utf-8")


def default_role(pack_dir: Path) -> str:
    roles = (yaml.safe_load((pack_dir / "roles.yaml").read_text(encoding="utf-8")) or {}).get("roles") or {}
    if not roles:
        raise SystemExit("error: the pack has no roles; pass --role")
    return next(iter(roles))


def cmd_stage_mode(a) -> int:
    if not re.fullmatch(r"[a-z0-9-]+", a.name):
        return fail("mode name: lowercase letters, digits and hyphens only")
    if a.into:
        pack_dir = Path(a.into).resolve()
        bump = False
    else:
        pack_dir = staging(a.task) / a.pack
        if not pack_dir.exists():
            shutil.copytree(installed_pack_dir(a.pack), pack_dir)
        bump = True
    mode_dir = pack_dir / "modes" / a.name
    if mode_dir.exists():
        return fail(f"{mode_dir} already exists")
    role = a.role or default_role(pack_dir)
    (mode_dir / "evals").mkdir(parents=True)
    fmt = {"pack": a.pack, "name": a.name, "summary": a.summary.replace('"', "'"), "role": role}
    (mode_dir / "mode.yaml").write_text(MODE_YAML.format(**fmt), encoding="utf-8")
    (mode_dir / "SKILL.md").write_text(SKILL_MD.format(**fmt), encoding="utf-8")
    golden = json.loads(json.dumps(GOLDEN).replace("{pack}", a.pack).replace("{name}", a.name))
    (mode_dir / "evals" / "golden-01.json").write_text(json.dumps(golden, indent=2) + "\n", encoding="utf-8")
    add_export(pack_dir / "pack.yaml", "modes", a.name)
    version = bump_minor(pack_dir / "pack.yaml") if bump else None
    print(json.dumps({"staged_pack": str(pack_dir.relative_to(ROOT)), "mode_dir": str(mode_dir.relative_to(ROOT)),
                      "pack_version": version}, indent=2))
    return 0


def cmd_stage_pack(a) -> int:
    if not re.fullmatch(r"[a-z0-9-]+", a.name) or a.name == "core":
        return fail("pack name: lowercase letters, digits and hyphens, and not 'core'")
    if (ROOT / "packs" / a.name).exists():
        return fail(f"packs/{a.name} already exists; use stage-mode to extend it")
    pack_dir = staging(a.task) / a.name
    if pack_dir.exists():
        return fail(f"{pack_dir} already exists")
    role = a.role or f"{a.name}-writer"
    for sub in ("modes", "skills/principles"):
        (pack_dir / sub).mkdir(parents=True, exist_ok=True)
        (pack_dir / sub / ".gitkeep").write_text("", encoding="utf-8")
    fmt = {"name": a.name, "summary": a.summary.replace('"', "'"), "role": role}
    (pack_dir / "pack.yaml").write_text(PACK_YAML.format(**fmt), encoding="utf-8")
    (pack_dir / "roles.yaml").write_text(ROLES_YAML.format(**fmt), encoding="utf-8")
    print(json.dumps({"staged_pack": str(pack_dir.relative_to(ROOT)), "role": role}, indent=2))
    return 0


def cmd_lint(a) -> int:
    base = Path(a.dir).resolve()
    problems = []
    if a.target:
        files = [base / c["path"] for c in changed_files(base, check_target(a.target))]
    else:
        files = sorted(p for p in base.rglob("*") if p.is_file())
    for f in files:
        try:
            text = f.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if "TODO" in line:
                problems.append(f"{f.relative_to(ROOT)}:{i}: unresolved TODO")
    for mode_yaml in [f for f in files if f.name == "mode.yaml"]:
        man = yaml.safe_load(mode_yaml.read_text(encoding="utf-8")) or {}
        skill = mode_yaml.parent / man.get("skill", "SKILL.md")
        if skill.exists():
            m = re.search(r"^name:\s*(\S+)", skill.read_text(encoding="utf-8"), flags=re.M)
            want = str(man.get("name", "")).replace("/", "-")
            if m and m.group(1) != want:  # the name is optional; `pmos render` generates it
                problems.append(f"{skill.relative_to(ROOT)}: frontmatter name should be '{want}'")
    if problems:
        print("FAIL")
        print("\n".join(f"- {p}" for p in problems))
        return 1
    print("PASS")
    return 0


def changed_files(staged: Path, target: Path) -> list[dict]:
    out = []
    for f in sorted(p for p in staged.rglob("*") if p.is_file()):
        relp = f.relative_to(staged)
        t = target / relp
        if not t.exists():
            out.append({"path": str(relp), "change": "added"})
        elif not filecmp.cmp(f, t, shallow=False):
            out.append({"path": str(relp), "change": "modified"})
    return out


def check_target(target: str) -> Path:
    t = (ROOT / target).resolve()
    if t.parent != (ROOT / "packs").resolve():
        raise SystemExit("error: --target must be packs/<name>")
    return t


def cmd_changes(a) -> int:
    print(json.dumps(changed_files(Path(a.staged).resolve(), check_target(a.target)), indent=2))
    return 0


def cmd_apply(a) -> int:
    staged, target = Path(a.staged).resolve(), check_target(a.target)
    wanted = set(a.files) if a.files else None
    applied = []
    for item in changed_files(staged, target):
        if wanted is not None and item["path"] not in wanted:
            continue
        dest = target / item["path"]
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(staged / item["path"], dest)
        applied.append(item)
    print(json.dumps({"applied": applied, "target": a.target}, indent=2))
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sm = sub.add_parser("stage-mode")
    for flag in ("--task", "--pack", "--name", "--summary"):
        sm.add_argument(flag, required=True)
    sm.add_argument("--role")
    sm.add_argument("--into")
    sm.set_defaults(fn=cmd_stage_mode)
    sp = sub.add_parser("stage-pack")
    for flag in ("--task", "--name", "--summary"):
        sp.add_argument(flag, required=True)
    sp.add_argument("--role")
    sp.set_defaults(fn=cmd_stage_pack)
    li = sub.add_parser("lint")
    li.add_argument("dir")
    li.add_argument("--target")
    li.set_defaults(fn=cmd_lint)
    ch = sub.add_parser("changes")
    ch.add_argument("staged")
    ch.add_argument("--target", required=True)
    ch.set_defaults(fn=cmd_changes)
    ap = sub.add_parser("apply")
    ap.add_argument("staged")
    ap.add_argument("--target", required=True)
    ap.add_argument("--files", nargs="*")
    ap.set_defaults(fn=cmd_apply)
    a = p.parse_args()
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())

"""forge — deterministic helpers for building pm-os modes and packs.

Everything is staged under outputs/<task id>/staged/ first. Nothing touches packs/ until the
Operator runs `apply` for an approved task.

  stage-mode --task ID --pack PACK --name NAME --summary TEXT [--role ROLE] [--into STAGED_PACK_DIR]
             [--script NAME ...] [--router]
      Copy the installed pack to the staging area (or use --into, a pack staged by forge/new-pack),
      add a skeleton mode with the eval@1 cases the coverage rule needs (a golden case and a failure
      case), export it, and bump the pack's minor version. --script adds modes/<mode>/scripts/NAME.py
      with a conformance case; --router makes the mode the pack's router, with a workflow case.
  stage-pack --task ID --name NAME --summary TEXT [--role ROLE]
      Create a skeleton pack in the staging area (with evals/conformance/ and evals/workflows/).
  lint [DIR] [--target packs/NAME]
      Fail on `TODO:` markers, on skill names that don't match their mode (a name is optional), on
      coverage gaps (`pmos eval --coverage DIR`) and on core's tightness lint (`pmos lint DIR`: word
      budgets, mode step structure, filler, copied principles or paragraphs). With DIR and --target,
      only the files this task added or changed are checked for markers (a new pack's files are all
      new); with only --target, DIR is the target and every file is checked.
  changes STAGED --target packs/NAME
      JSON list of files added or modified relative to the target.
  apply STAGED --target packs/NAME [--files PATH ...]
      Copy staged files into packs/. STAGED must be outputs/<id>/staged/<pack> of an approved task.
  sync-action ACTION.json
      The `repo.sync_pack` handler `pmos action run` calls: `apply` with the action's payload.
"""
from __future__ import annotations

import argparse
import filecmp
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import yaml


def find_root() -> Path:
    """The pm-os repo: PMOS_ROOT, else the nearest folder above this script that holds pm-os.yaml."""
    if os.environ.get("PMOS_ROOT"):
        return Path(os.environ["PMOS_ROOT"]).resolve()
    for d in Path(__file__).resolve().parents:
        if (d / "pm-os.yaml").exists() and (d / "scripts" / "pmos.py").exists():
            return d
    raise SystemExit("error: can't find the pm-os repo (no pm-os.yaml above this script); set PMOS_ROOT")


ROOT = find_root()
PACKS_ROOT = Path(__file__).resolve().parents[1].parent   # new packs are created beside this one

MODE_YAML = """name: {pack}/{name}
version: 0.1.0
contract: task@1
summary: "{summary}"
verbs: [draft]                    # TODO: pick from plan | draft | analyze | execute | review
accepts:
  goal: string                    # TODO: the real inputs; a trailing ? marks optional
returns:                          # types: string number integer bool list object doc_ref diff_ref
  doc: doc_ref                    # TODO: the real outputs (results carry them in `outputs`)
skill: SKILL.md
default_role: {role}
calls: []                         # modes this one may start as children, version-pinned
grants: {{}}                        # TODO: e.g. {{ jira: read, docs: draft }}
approval: before_publish          # TODO: none | before_publish | before_execute
risk: medium
principles: []                    # cite existing principles before writing new ones
done:                             # the definition of done
  must:                           # every line must hold, or the review fails
    - "TODO: one outcome a reviewer can check in the artifact"
    # - code: "python packs/{pack}/modes/{name}/scripts/<script>.py {{outputs.doc}}"   # run by pmos at task result
    # - principle: <a principle this mode must meet>
  should:                         # the share that holds sets the score
    - "TODO: one line that makes the work better"
evals: evals/
"""

SKILL_MD = """---
description: "{summary}. Use when a Worker has been given a pm-os task whose envelope mode is {pack}/{name}."
---
# {pack}/{name}

1. `[code: python scripts/pmos.py task show <id>]` — the envelope, role, principles and notes.
2. `[model]` TODO: replace with the steps, each tagged and at most 60 words; cite principles and skills by name.
3. `[code: python scripts/pmos.py task result <id> outputs/<id>/result.json]` — TODO: what the
   result carries (status, artifacts, outputs, actions).
"""

GOLDEN = {
    "kind": "golden",
    "name": "TODO: what this case proves (the main path)",
    "covers": ["mode:{pack}/{name}"],
    "envelope": {"verb": "draft", "mode": "{pack}/{name}", "inputs": {"goal": "TODO: a realistic input"},
                 "acceptance": ["TODO: an acceptance line"], "risk": "medium", "approval": "before_publish"},
    "expect": ["TODO: a line a grader can check"],
}

GOLDEN_FAIL = {
    "kind": "golden",
    "name": "TODO: the failure path this case proves (a gate, a refusal, a missing input)",
    "covers": ["mode:{pack}/{name}"],
    "failure": True,
    "envelope": {"verb": "draft", "mode": "{pack}/{name}", "inputs": {"goal": "TODO: an input the mode must not guess on"},
                 "risk": "medium", "approval": "before_publish"},
    "expect": ["TODO: e.g. the result is status blocked with one open question, and no actions"],
}

WORKFLOW = {
    "kind": "golden",
    "name": "TODO: a goal this router turns into a plan of the pack's modes",
    "covers": ["router:{pack}/{name}", "mode:{pack}/{name}"],
    "envelope": {"verb": "plan", "mode": "{pack}/{name}", "inputs": {"goal": "TODO: a goal-level ask"},
                 "risk": "medium", "approval": "none"},
    "expect": ["TODO: which child modes the plan runs, and how their outputs are wired ($from)"],
}

SCRIPT_PY = '''"""{script} — a codified step of {pack}/{name}.

TODO: what it reads, what it prints, and its exit codes.
"""
import argparse
import sys


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.parse_args()
    return 0


if __name__ == "__main__":
    sys.exit(main())
'''

SCRIPT_CASE = """kind: conformance
name: {case}
covers: [script:modes/{name}/scripts/{script}.py]
desc: "TODO: what {script}.py must do, on a fixture in evals/fixtures/"
steps:
  - run: $PY $PACK/modes/{name}/scripts/{script}.py --help
    expect: {{stdout: 'usage'}}
"""

PACK_YAML = """name: {name}
version: 0.1.0
contract: pack@1
summary: "{summary}"
requires:
  core: ^0.4
depends: []                       # other packs this one uses, e.g. [pm@^0.3]
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
    effort: medium                # implementers run at medium; reviewers at high
    persona: "TODO: who this role is, in one sentence"
    skills: [core:infra/envelope-io, core:infra/self-check]
    context: []
    principles: []
    rubric: []
"""


def fail(msg: str) -> int:
    print(f"error: {msg}", file=sys.stderr)
    return 1


def rel(path: Path) -> str:
    """PATH relative to the repo when it is inside it (the outputs folder may be elsewhere)."""
    try:
        return str(Path(path).resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


def pmos(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(ROOT / "scripts" / "pmos.py"), *args], cwd=ROOT,
                          capture_output=True, text=True)


def installed_pack_dir(pack: str, required: bool = True) -> Path | None:
    proc = pmos("pack", "path", pack)
    if proc.returncode != 0:
        if required:
            raise SystemExit(f"error: pack '{pack}' is not installed")
        return None
    return Path(proc.stdout.strip()).resolve()


def outputs_dir() -> Path:
    """The outputs folder, from `pmos path outputs` (it applies the outputs override)."""
    proc = pmos("path", "outputs")
    if proc.returncode != 0:
        raise SystemExit(f"error: `pmos path outputs` failed: {proc.stderr.strip()}")
    return Path(proc.stdout.strip()).resolve()


def staging(task: str) -> Path:
    return outputs_dir() / task / "staged"


def check_staged(staged: Path, task_id: str | None = None) -> None:
    """STAGED must be outputs/<id>/staged/<pack> of a task that is approved (and, when given, task_id)."""
    try:
        parts = staged.relative_to(outputs_dir()).parts
    except ValueError:
        parts = ()
    if len(parts) < 3 or parts[1] != "staged" or (task_id and parts[0] != task_id):
        raise SystemExit(f"error: {staged} is not under outputs/<task id>/staged/"
                         + (f" of task {task_id}" if task_id else "") + "; apply copies only staged work")
    proc = pmos("task", "state", parts[0])
    state = proc.stdout.strip() if proc.returncode == 0 else None
    if state != "approved":
        raise SystemExit(f"error: task {parts[0]} is {state or 'unknown'}, not approved; "
                         f"staged work is applied only after the PM approves it")


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


def set_router(pack_yaml: Path, mode: str) -> None:
    text = pack_yaml.read_text(encoding="utf-8")
    line = f"router: {mode}"
    if re.search(r"^router:.*$", text, flags=re.M):
        text = re.sub(r"^router:.*$", line, text, count=1, flags=re.M)
    else:
        text = re.sub(r"^(exports:)", line + "\n\\1", text, count=1, flags=re.M)
    pack_yaml.write_text(text, encoding="utf-8")


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
    def case(template: dict) -> str:
        return json.dumps(json.loads(json.dumps(template).replace("{pack}", a.pack).replace("{name}", a.name)),
                          indent=2) + "\n"
    # eval@1 coverage: a golden case and a failure-path case per mode
    (mode_dir / "evals" / "golden-01.json").write_text(case(GOLDEN), encoding="utf-8")
    (mode_dir / "evals" / "golden-fail.json").write_text(case(GOLDEN_FAIL), encoding="utf-8")
    written = []
    for script in a.script or []:                      # a script needs a conformance case
        if not re.fullmatch(r"[a-z0-9_]+", script):
            return fail("script name: lowercase letters, digits and underscores only")
        (mode_dir / "scripts").mkdir(exist_ok=True)
        (mode_dir / "scripts" / f"{script}.py").write_text(SCRIPT_PY.format(script=script, pack=a.pack, name=a.name),
                                                           encoding="utf-8")
        cname = f"{a.name}-{script.replace('_', '-')}"
        (pack_dir / "evals" / "conformance").mkdir(parents=True, exist_ok=True)
        (pack_dir / "evals" / "conformance" / f"{cname}.yaml").write_text(
            SCRIPT_CASE.format(case=cname, name=a.name, script=script), encoding="utf-8")
        written.append(rel(pack_dir / "evals" / "conformance" / f"{cname}.yaml"))
    if a.router:                                       # a router needs a workflow case
        set_router(pack_dir / "pack.yaml", a.name)
        (pack_dir / "evals" / "workflows").mkdir(parents=True, exist_ok=True)
        (pack_dir / "evals" / "workflows" / f"{a.name}-01.json").write_text(case(WORKFLOW), encoding="utf-8")
        written.append(rel(pack_dir / "evals" / "workflows" / f"{a.name}-01.json"))
    add_export(pack_dir / "pack.yaml", "modes", a.name)
    version = bump_minor(pack_dir / "pack.yaml") if bump else None
    print(json.dumps({"staged_pack": rel(pack_dir), "mode_dir": rel(mode_dir), "cases": written,
                      "pack_version": version}, indent=2))
    return 0


def cmd_stage_pack(a) -> int:
    if not re.fullmatch(r"[a-z0-9-]+", a.name) or a.name == "core":
        return fail("pack name: lowercase letters, digits and hyphens, and not 'core'")
    if (PACKS_ROOT / a.name).exists():
        return fail(f"{PACKS_ROOT.name}/{a.name} already exists; use stage-mode to extend it")
    pack_dir = staging(a.task) / a.name
    if pack_dir.exists():
        return fail(f"{pack_dir} already exists")
    role = a.role or f"{a.name}-writer"
    for sub in ("modes", "skills/principles", "evals/conformance", "evals/workflows"):
        (pack_dir / sub).mkdir(parents=True, exist_ok=True)
        (pack_dir / sub / ".gitkeep").write_text("", encoding="utf-8")
    fmt = {"name": a.name, "summary": a.summary.replace('"', "'"), "role": role}
    (pack_dir / "pack.yaml").write_text(PACK_YAML.format(**fmt), encoding="utf-8")
    (pack_dir / "roles.yaml").write_text(ROLES_YAML.format(**fmt), encoding="utf-8")
    print(json.dumps({"staged_pack": rel(pack_dir), "role": role}, indent=2))
    return 0


TODO_MARK = re.compile(r"\bTODO:")   # the marker forge's skeletons use


def cmd_lint(a) -> int:
    if not a.dir and not a.target:
        return fail("give DIR, --target packs/NAME, or both")
    base = Path(a.dir or a.target).resolve()
    if not base.is_dir():
        return fail(f"{a.dir or a.target} is not a folder")
    problems = []
    if a.dir and a.target:
        files = [base / c["path"] for c in changed_files(base, check_target(a.target))]
    else:
        files = sorted(p for p in base.rglob("*") if p.is_file() and "__pycache__" not in p.parts)
    for f in files:
        try:
            text = f.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if TODO_MARK.search(line):
                problems.append(f"{rel(f)}:{i}: unresolved TODO: marker")
    for mode_yaml in [f for f in files if f.name == "mode.yaml"]:
        man = yaml.safe_load(mode_yaml.read_text(encoding="utf-8")) or {}
        skill = mode_yaml.parent / man.get("skill", "SKILL.md")
        if skill.exists():
            m = re.search(r"^name:\s*(\S+)", skill.read_text(encoding="utf-8"), flags=re.M)
            want = str(man.get("name", "")).replace("/", "-")
            if m and m.group(1) != want:  # the name is optional; `pmos render` generates it
                problems.append(f"{rel(skill)}: frontmatter name should be '{want}'")
    if (base / "pack.yaml").exists():                # eval@1 coverage of the whole pack
        cov = pmos("eval", "--coverage", str(base))
        problems += [ln.strip()[2:] for ln in cov.stdout.splitlines() if ln.startswith("  - ")]
        if cov.returncode not in (0, 1):
            problems.append(f"`pmos eval --coverage` failed: {(cov.stderr or cov.stdout).strip()[-300:]}")
        tight = pmos("lint", str(base), "--json")      # core's tightness lint, on the whole pack
        try:
            report = json.loads(tight.stdout)
            problems += report["error_lines"]
            for w in report["warning_lines"]:
                print(f"warn: {w}")
        except (json.JSONDecodeError, KeyError):
            problems.append(f"`pmos lint` failed: {(tight.stderr or tight.stdout).strip()[-300:]}")
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
    """An installed pack's directory, or a new pack's beside the installed ones."""
    t = (ROOT / target).resolve()
    installed = installed_pack_dir(t.name, required=False)
    if (installed and t != installed) or (not installed and t.parent != PACKS_ROOT):
        raise SystemExit(f"error: --target must be an installed pack's directory or {PACKS_ROOT.name}/<new pack>")
    return t


def cmd_changes(a) -> int:
    print(json.dumps(changed_files(Path(a.staged).resolve(), check_target(a.target)), indent=2))
    return 0


def cmd_apply(a, task_id: str | None = None) -> int:
    staged = Path(a.staged).resolve()
    check_staged(staged, task_id)
    target = check_target(a.target)
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


def cmd_sync_action(a) -> int:
    spec = json.loads(Path(a.action_file).read_text(encoding="utf-8"))
    payload = (spec.get("action") or {}).get("payload") or {}
    if not payload.get("staged") or not payload.get("target"):
        return fail("a repo.sync_pack payload needs 'staged' and 'target'")
    args = argparse.Namespace(staged=str(ROOT / payload["staged"]), target=payload["target"],
                              files=payload.get("files"))
    return cmd_apply(args, task_id=spec.get("task_id") or "?")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sm = sub.add_parser("stage-mode")
    for flag in ("--task", "--pack", "--name", "--summary"):
        sm.add_argument(flag, required=True)
    sm.add_argument("--role", help="the role to run it (default: the pack's first role)")
    sm.add_argument("--into", help="a pack staged by forge/new-pack (no copy, no version bump)")
    sm.add_argument("--script", action="append", help="add modes/<mode>/scripts/SCRIPT.py and its conformance case")
    sm.add_argument("--router", action="store_true", help="make this mode the pack's router, with a workflow case")
    sm.set_defaults(fn=cmd_stage_mode)
    sp = sub.add_parser("stage-pack")
    for flag in ("--task", "--name", "--summary"):
        sp.add_argument(flag, required=True)
    sp.add_argument("--role")
    sp.set_defaults(fn=cmd_stage_pack)
    li = sub.add_parser("lint")
    li.add_argument("dir", nargs="?", help="the staged pack (default: --target)")
    li.add_argument("--target", help="packs/NAME: with DIR, lint only the files DIR adds or changes")
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
    sa = sub.add_parser("sync-action")
    sa.add_argument("action_file")
    sa.set_defaults(fn=cmd_sync_action)
    a = p.parse_args()
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())

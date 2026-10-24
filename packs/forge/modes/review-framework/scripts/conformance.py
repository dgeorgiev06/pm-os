#!/usr/bin/env python3
"""Run the framework conformance evals for one review aspect on a scratch copy (a codified step of
forge/review-framework). The tree under review is never modified; output goes to outputs/<id>/.

  conformance.py --task ID --aspect clarity|performance|modularity|composability|tightness [--ref REF] [--case GLOB]
      Copy the tree under review to a scratch folder (default: the working tree; REF may be a path
      or a git ref, extracted with `git archive`), run
      `python scripts/pmos.py eval --framework <aspect> --json` there (--case narrows the cases), and
      write outputs/<id>/conformance.json and conformance.md. For tightness, first run
      `python scripts/pmos.py lint --json` there and write outputs/<id>/lint.json. Records
      `git status` first.
  conformance.py --task ID --verify-clean
      Exit 1 if the repo's HEAD or `git status --porcelain` changed since the run above.

Run it from the repo root. Output goes to `pmos path outputs`/<id>/.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ASPECTS = ("clarity", "performance", "modularity", "composability", "tightness")
SKIP_TOP = {".git", "build", ".claude", "CLAUDE.md", "__pycache__"}


def fail(msg: str, code: int = 2) -> int:
    print(f"error: {msg}", file=sys.stderr)
    return code


def repo_root() -> Path:
    root = Path.cwd()
    if not (root / "scripts" / "pmos.py").exists():
        raise SystemExit("error: run this from the pm-os repo root (scripts/pmos.py not found)")
    return root


def out_dir(root: Path, task: str) -> Path:
    proc = subprocess.run([sys.executable, "scripts/pmos.py", "path", "outputs"], cwd=root, capture_output=True, text=True)
    if proc.returncode != 0:
        raise SystemExit(f"error: `pmos path outputs` failed: {proc.stderr.strip()}")
    d = Path(proc.stdout.strip()) / task
    d.mkdir(parents=True, exist_ok=True)
    return d


def git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)


def snapshot(root: Path) -> dict:
    head = git(root, "rev-parse", "HEAD")
    status = git(root, "status", "--porcelain")
    return {"head": head.stdout.strip() if head.returncode == 0 else None,
            "status": status.stdout if status.returncode == 0 else None}


def copy_tree(src: Path, dest: Path) -> None:
    def ignore(dirpath: str, names: list[str]) -> set[str]:
        rel = Path(dirpath).resolve().relative_to(src.resolve())
        skip = {n for n in names if n == "__pycache__"}
        if not rel.parts:
            skip |= {n for n in names if n in SKIP_TOP}
        if rel.parts in (("outputs",), ("traces",)):
            skip |= {n for n in names if n != ".gitkeep"}
        if rel.parts == ("state",):
            skip |= {n for n in names if n == "tasks"}
        return skip
    shutil.copytree(src, dest, ignore=ignore)


def materialize(root: Path, ref: str | None, dest: Path) -> str:
    if ref is None:
        copy_tree(root, dest)
        return "working tree"
    path = Path(ref)
    if path.is_dir():
        copy_tree(path.resolve(), dest)
        return f"path {ref}"
    if git(root, "rev-parse", "--verify", f"{ref}^{{commit}}").returncode != 0:
        raise SystemExit(f"error: '{ref}' is neither a folder nor a git ref")
    dest.mkdir(parents=True)
    archive = subprocess.run(["git", "-C", str(root), "archive", ref], capture_output=True)
    if archive.returncode != 0:
        raise SystemExit(f"error: git archive {ref} failed: {archive.stderr.decode(errors='replace')}")
    subprocess.run(["tar", "-x", "-C", str(dest)], input=archive.stdout, check=True)
    return f"git ref {ref}"


def run_lint(tree: Path) -> dict:
    """`pmos lint --json` on the tree under review (the code half of a tightness review)."""
    proc = subprocess.run([sys.executable, "scripts/pmos.py", "lint", "--json"], cwd=tree, capture_output=True,
                          text=True, timeout=600)
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        raise SystemExit(f"error: `pmos lint --json` didn't return JSON in the tree under review (exit "
                         f"{proc.returncode}); it needs core 0.3.1 or later:\n{proc.stdout[-800:]}{proc.stderr[-800:]}")


def run_evals(root: Path, tree: Path, aspect: str, scratch: Path, case: str | None = None) -> tuple[dict, str]:
    narrow = ["--case", case] if case else []
    if (tree / "scripts" / "framework_eval.py").exists() and (tree / "evals" / "framework" / aspect).is_dir():
        cmd = [sys.executable, "scripts/pmos.py", "eval", "--framework", aspect, "--json", *narrow]
        cwd, shown = tree, f"python scripts/pmos.py eval --framework {aspect} --json  (in a scratch copy)"
    else:  # an older tree without the evals: run today's cases against it
        cmd = [sys.executable, str(root / "scripts" / "framework_eval.py"), aspect, "--json", "--root", str(tree),
               "--cases-dir", str(root / "evals" / "framework"), "--out", str(scratch / "latest.json"), *narrow]
        cwd = scratch
        shown = f"python scripts/framework_eval.py {aspect} --json --root <scratch copy>  (today's cases, older tree)"
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=1800)
    try:
        return json.loads(proc.stdout), shown
    except json.JSONDecodeError:
        raise SystemExit(f"error: the conformance evals didn't return JSON (exit {proc.returncode}):\n"
                         f"{proc.stdout[-1500:]}\n{proc.stderr[-1500:]}")


def markdown(summary: dict, aspect: str, source: str) -> str:
    lines = [f"# Conformance: {aspect} ({source})", "",
             f"{summary['passed']} passed, {summary['failed']} failed.", "",
             "| Case | Finding | Kind | Result | First failing expectation |",
             "| --- | --- | --- | --- | --- |"]
    for c in summary["cases"]:
        failure = (c.get("failure") or "").replace("|", "/").replace("\n", " ")
        lines.append(f"| `{c['name']}` | {c.get('finding') or ''} | {'regression' if c.get('regression') else 'conformance'} | "
                     f"{c['result']} | {failure[:200]} |")
    return "\n".join(lines) + "\n"


def cmd_run(a) -> int:
    if a.aspect not in ASPECTS:
        return fail(f"aspect must be one of {', '.join(ASPECTS)} (got '{a.aspect}')")
    root = repo_root()
    out = out_dir(root, a.task)
    before = snapshot(root)
    (out / "git-before.json").write_text(json.dumps(before, indent=2) + "\n", encoding="utf-8")
    scratch = Path(tempfile.mkdtemp(prefix="pmos-review-"))
    try:
        source = materialize(root, a.ref, scratch / "tree")
        lint = run_lint(scratch / "tree") if a.aspect == "tightness" else None
        summary, command = run_evals(root, scratch / "tree", a.aspect, scratch, a.case)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    summary["source"] = {"aspect": a.aspect, "ref": a.ref, "reviewed": source, "command": command}
    (out / "conformance.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    (out / "conformance.md").write_text(markdown(summary, a.aspect, source), encoding="utf-8")
    if lint is not None:
        (out / "lint.json").write_text(json.dumps(lint, indent=2) + "\n", encoding="utf-8")
    reg = sum(1 for c in summary["cases"] if c.get("regression") and c["result"] != "pass")
    print(f"{a.aspect} ({source}): {summary['passed']} passed, {summary['failed']} failed"
          + (f", {reg} regression case(s) failing" if reg else "")
          + (f"; lint: {len(lint['files'])} file(s), {lint['errors']} error(s), {lint['warnings']} warning(s)"
             if lint is not None else "")
          + f" -> {out / 'conformance.json'}")
    return 0


def cmd_verify(a) -> int:
    root = repo_root()
    f = out_dir(root, a.task) / "git-before.json"
    if not f.exists():
        return fail(f"no {f}; run with --aspect first")
    before, now = json.loads(f.read_text(encoding="utf-8")), snapshot(root)
    if before != now:
        print("CHANGED: the repo under review differs from before the review")
        print(f"before: HEAD {before['head']}\n{before['status'] or '(clean)'}")
        print(f"now:    HEAD {now['head']}\n{now['status'] or '(clean)'}")
        return 1
    print("clean: the repo under review is unchanged")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--task", required=True, help="the forge/review-framework task id")
    p.add_argument("--aspect", help="clarity, performance, modularity, composability or tightness")
    p.add_argument("--case", help="only the core cases whose name matches this glob")
    p.add_argument("--ref", help="a git ref or a folder to review (default: the working tree)")
    p.add_argument("--verify-clean", action="store_true", help="check the repo is unchanged since the run")
    a = p.parse_args()
    if a.verify_clean:
        return cmd_verify(a)
    if not a.aspect:
        return fail("give --aspect (or --verify-clean)")
    return cmd_run(a)


if __name__ == "__main__":
    sys.exit(main())

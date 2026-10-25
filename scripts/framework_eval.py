#!/usr/bin/env python3
"""framework_eval — the conformance runner of pm-os (eval@1, kind `conformance`). No model.

Core's cases are YAML files in evals/framework/<group>/; a pack's are in packs/<pack>/evals/conformance/
(see evals/framework/README.md for the format). A case runs in a fresh temporary copy of the repo (for
a pack: of its sandbox, see `pmos eval`); its steps are shell commands run with cwd = that copy, and
each step's expectations are checked before the next step runs. `pmos eval` calls run_cases().

  python scripts/framework_eval.py [REVIEW ...] [--case GLOB] [--json] [--root DIR] [--out FILE]
  python scripts/pmos.py eval --framework [REVIEW ...] [--case GLOB] [--json]

Prints a pass/fail table, writes a JSON summary (default build/framework-evals/latest.json) and
exits non-zero if any case fails.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import datetime as dt
import fnmatch
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
REVIEWS = ["clarity", "performance", "modularity", "composability", "eval-standard", "effort", "dispatch",
           "tightness", "cos-thread", "done", "standards", "overlays", "sends", "channels"]
CORE_CTX = {"pack": "core", "pack_rel": ".", "fx_rel": "evals/framework/fixtures", "sync_fixtures": True}
CHAIN_VAR = "PMOS_CONFORMANCE_CHAIN"   # the cases running above this one, so a case never runs itself
STEP_TIMEOUT = 180
CASE_KEYS = {"name", "finding", "owner", "severity", "desc", "regression", "setup", "steps", "kind", "covers", "failure"}
STEP_KEYS = {"name", "run", "capture", "expect"}
EXPECT_KEYS = {"exit", "stdout", "stdout_not", "stderr", "stderr_not", "output", "output_not",
               "task", "files"}


class CaseError(Exception):
    """A case file is malformed (not a failing expectation)."""


# --------------------------------------------------------------------------- loading
def load_cases(cases_dir: Path, reviews: list[str], pattern: str | None) -> list[dict]:
    out = []
    for review in reviews:
        d = cases_dir / review
        for f in sorted(d.glob("*.yaml")):
            case = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
            case["_file"] = str(f.relative_to(cases_dir.parent.parent)) if cases_dir.parent.parent in f.parents else str(f)
            case.setdefault("owner", review)
            if pattern and not fnmatch.fnmatch(case.get("name", ""), pattern):
                continue
            out.append(case)
    return out


def check_case_shape(case: dict) -> None:
    unknown = set(k for k in case if not k.startswith("_")) - CASE_KEYS
    if unknown:
        raise CaseError(f"unknown case keys {sorted(unknown)}")
    if case.get("kind", "conformance") != "conformance":
        raise CaseError(f"kind is {case.get('kind')!r}; this runner runs conformance cases only")
    for k in ("name", "owner", "steps"):
        if not case.get(k):
            raise CaseError(f"case is missing '{k}'")
    for i, s in enumerate(case["steps"], 1):
        if not isinstance(s, dict) or "run" not in s:
            raise CaseError(f"step {i} needs 'run'")
        bad = set(s) - STEP_KEYS
        if bad:
            raise CaseError(f"step {i}: unknown keys {sorted(bad)}")
        bad = set(s.get("expect") or {}) - EXPECT_KEYS
        if bad:
            raise CaseError(f"step {i}: unknown expect keys {sorted(bad)}")


# --------------------------------------------------------------------------- the copy
def ignore_for(src_root: Path):
    def ignore(dirpath: str, names: list[str]) -> set[str]:
        rel = Path(dirpath).resolve().relative_to(src_root)
        skip = {n for n in names if n in (".git", "__pycache__") or n.endswith(".tmp")}
        top = rel.parts[0] if rel.parts else ""
        if not rel.parts:
            skip |= {n for n in names if n in ("build", ".claude", "CLAUDE.md")}
        if rel.parts == ("state",):
            skip |= {n for n in names if n == "tasks"}
        if top in ("traces", "outputs") and len(rel.parts) == 1:
            skip |= {n for n in names if n != ".gitkeep"}
        if rel.parts == ("context",):
            skip |= {n for n in names if n == "todos.yaml"}
        return skip
    return ignore


def make_copy(src_root: Path, cases_dir: Path | None, base: Path) -> Path:
    dest = base / "repo"
    shutil.copytree(src_root, dest, ignore=ignore_for(src_root.resolve()), symlinks=True)
    for d in ("traces", "outputs", "state"):
        (dest / d).mkdir(exist_ok=True)
    # Core's cases and fixtures always come from the cases dir, even when --root is another tree.
    if cases_dir is None:
        return dest
    fx_src = cases_dir / "fixtures"
    fx_dest = dest / "evals" / "framework" / "fixtures"
    if fx_src.resolve() != fx_dest.resolve():
        shutil.rmtree(fx_dest, ignore_errors=True)
        shutil.copytree(fx_src, fx_dest)
    return dest


def step_env(copy: Path, values: dict[str, str], ctx: dict | None = None, chain: str = "") -> dict[str, str]:
    ctx = ctx or CORE_CTX
    env = {k: v for k, v in os.environ.items() if not k.startswith("PMOS_")}
    py = sys.executable
    env.update({
        "PY": py,
        "PMOS": f"{py} scripts/pmos.py",
        "FORGE": f"{py} packs/forge/scripts/forge.py",
        "TODOS": f"{py} packs/cos/scripts/todos.py",
        "FX": ctx["fx_rel"],                          # the case's own fixtures (core's, or the pack's)
        "PACK": ctx["pack_rel"],                      # the pack under test, relative to the copy
        "CORE_BIN": "evals/framework/fixtures/bin",   # core's helpers (mkresult.py, advance.py, yset.py ...)
        "REPO": str(copy),
        "PYTHONDONTWRITEBYTECODE": "1",
        CHAIN_VAR: chain,
    })
    env.update(values)
    return env


# --------------------------------------------------------------------------- expectations
VAR = re.compile(r"\$\{(\w+)\}|\$(\w+)")


def subst(text, values: dict[str, str]):
    if isinstance(text, str):
        return VAR.sub(lambda m: values.get(m.group(1) or m.group(2), m.group(0)), text)
    if isinstance(text, list):
        return [subst(t, values) for t in text]
    if isinstance(text, dict):
        return {subst(k, values): subst(v, values) for k, v in text.items()}
    return text


def as_list(x) -> list:
    if x is None:
        return []
    return x if isinstance(x, list) else [x]


def short(text: str, n: int = 160) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[: n - 1] + "…"


def last_lines(text: str, n: int = 2) -> str:
    lines = [l for l in text.strip().splitlines() if l.strip()]
    return " / ".join(lines[-n:])


def get_path(data, dotted: str):
    cur = data
    for part in dotted.split("."):
        if isinstance(cur, list) and part.isdigit():
            idx = int(part)
            if idx >= len(cur):
                raise KeyError(dotted)
            cur = cur[idx]
        elif isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            raise KeyError(dotted)
    return cur


def load_task_state(copy: Path, env: dict, task_id: str) -> dict | None:
    p = copy / "state" / "tasks" / f"{task_id}.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    proc = subprocess.run([sys.executable, "scripts/pmos.py", "task", "show", task_id, "--json"], cwd=copy,
                          env=env, capture_output=True, text=True, timeout=STEP_TIMEOUT)
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None


def expand(copy: Path, pattern: str) -> list[Path]:
    return [Path(p) for p in sorted(glob.glob(str(copy / pattern), recursive=True))]


def check_expect(expect: dict, proc, copy: Path, env: dict, values: dict) -> str | None:
    """Return a description of the first failing expectation, or None."""
    expect = subst(expect or {}, values)
    out, err = proc.stdout, proc.stderr
    both = out + ("\n" if out and err else "") + err
    want = expect.get("exit", 0)
    code = proc.returncode
    if want == "nonzero":
        if code == 0:
            return f"expected a non-zero exit, got 0 (stdout: {short(last_lines(out))})"
    elif want != "any":
        if code != int(want):
            return f"expected exit {want}, got {code}: {short(last_lines(both))}"
    for key, text in (("stdout", out), ("stderr", err), ("output", both)):
        for rx in as_list(expect.get(key)):
            if not re.search(rx, text, flags=re.M):
                return f"{key} should match /{rx}/; got: {short(last_lines(text, 3))}"
        for rx in as_list(expect.get(f"{key}_not")):
            m = re.search(rx, text, flags=re.M)
            if m:
                line = text[text.rfind("\n", 0, m.start()) + 1: text.find("\n", m.end()) if text.find("\n", m.end()) != -1 else None]
                return f"{key} should not match /{rx}/; found: {short(line)}"
    t = expect.get("task")
    if t:
        tid = t.get("id")
        task = load_task_state(copy, env, tid)
        if task is None:
            return f"task {tid}: no state found"
        if "state" in t and not re.search(f"^(?:{t['state']})$", str(task.get("state"))):
            return f"task {tid}: state should be {t['state']}, is {task.get('state')}"
        for path, rx in (t.get("fields") or {}).items():
            try:
                val = get_path(task, path)
            except KeyError:
                return f"task {tid}: field '{path}' is missing"
            sval = val if isinstance(val, str) else json.dumps(val, sort_keys=True)
            if not re.search(str(rx), sval, flags=re.M):
                return f"task {tid}: field '{path}' should match /{rx}/, is {short(sval, 120)}"
        for path in as_list(t.get("absent")):
            try:
                get_path(task, path)
                return f"task {tid}: field '{path}' should be absent"
            except KeyError:
                pass
    f = expect.get("files") or {}
    for pat in as_list(f.get("exists")):
        if not expand(copy, pat):
            return f"file {pat} should exist"
    for pat in as_list(f.get("absent")):
        hits = expand(copy, pat)
        if hits:
            return f"file {pat} should not exist (found {hits[0].relative_to(copy)})"
    for key, negate in (("contains", False), ("not_contains", True)):
        for pat, rxs in (f.get(key) or {}).items():
            hits = [p for p in expand(copy, pat) if p.is_file()]
            if not hits:
                return f"file {pat} should exist (to check its contents)"
            for p in hits:
                text = p.read_text(encoding="utf-8", errors="replace")
                for rx in as_list(rxs):
                    found = re.search(rx, text, flags=re.M)
                    if negate and found:
                        return f"{p.relative_to(copy)} should not match /{rx}/ (found: {short(found.group(0), 80)})"
                    if not negate and not found:
                        return f"{p.relative_to(copy)} should match /{rx}/"
    return None


# --------------------------------------------------------------------------- running
def run_shell(cmd: str, copy: Path, env: dict):
    try:
        return subprocess.run(["bash", "-c", cmd], cwd=copy, env=env, capture_output=True, text=True,
                              timeout=STEP_TIMEOUT)
    except subprocess.TimeoutExpired as e:
        return subprocess.CompletedProcess(cmd, 124, e.stdout or "", (e.stderr or "") + "\n[timeout]")


def do_setup(case: dict, copy: Path, env: dict, ctx: dict | None = None) -> str | None:
    setup = case.get("setup") or {}
    fx = copy / (ctx or CORE_CTX)["fx_rel"]
    for src, dest in (setup.get("copy") or {}).items():
        s = fx / src if not src.startswith("/") else Path(src)
        if not s.exists():
            return f"setup: fixture {src} not found"
        d = copy / dest
        if s.is_dir():
            shutil.copytree(s, d, dirs_exist_ok=True)
        else:
            d.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(s, d)
    for path, content in (setup.get("files") or {}).items():
        p = copy / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content if isinstance(content, str) else json.dumps(content, indent=2), encoding="utf-8")
    for name in as_list(setup.get("install")):
        src = fx / "packs" / name
        if not src.exists():
            return f"setup: fixture pack {name} not found"
        shutil.copytree(src, copy / "packs" / name, dirs_exist_ok=True)
        proc = run_shell(f'$PMOS pack add packs/{name} --approve-grants', copy, env)
        if proc.returncode != 0:
            return f"setup: installing fixture pack {name} failed: {short(last_lines(proc.stdout + proc.stderr, 3))}"
    return None


def run_case(case: dict, src_root: Path, cases_dir: Path | None, keep: bool, ctx: dict | None = None) -> dict:
    ctx = ctx or CORE_CTX
    started = time.time()
    rec = {"name": case.get("name"), "finding": case.get("finding"), "owner": case.get("owner"),
           "severity": case.get("severity"), "regression": bool(case.get("regression")),
           "file": case.get("_file"), "result": "pass", "failure": None, "step": None,
           "pack": ctx["pack"], "kind": "conformance", "covers": list(case.get("covers") or []),
           "failure_path": bool(case.get("failure"))}
    key = f"{ctx['pack']}/{case.get('name')}"
    above = [c for c in os.environ.get(CHAIN_VAR, "").split(":") if c]
    if key in above:  # e.g. a case that runs `pmos eval --all`: it would run itself forever
        rec.update(result="skipped", failure="skipped: this case is already running further up")
        rec["seconds"] = 0.0
        return rec
    chain = ":".join(above + [key])
    base = Path(tempfile.mkdtemp(prefix="pmos-feval-"))  # no case name: keywords in paths would leak into regexes
    try:
        check_case_shape(case)
        copy = make_copy(src_root, cases_dir if ctx.get("sync_fixtures") else None, base)
        values: dict[str, str] = {}
        env = step_env(copy, values, ctx, chain)
        problem = do_setup(case, copy, env, ctx)
        if problem:
            rec.update(result="fail", failure=problem, step=0)
            return rec
        for i, step in enumerate(case["steps"], 1):
            env = step_env(copy, values, ctx, chain)
            proc = run_shell(step["run"], copy, env)
            for var, rx in (step.get("capture") or {}).items():
                rxs = subst(rx, values)
                found = list(re.finditer(rxs, proc.stdout, flags=re.M)) or list(re.finditer(rxs, proc.stderr, flags=re.M))
                m = found[-1] if found else None  # the last match: chained commands print earlier ids first
                if not m:
                    rec.update(result="fail", step=i,
                               failure=f"step {i}: capture {var} /{rx}/ not found in output "
                                       f"(exit {proc.returncode}: {short(last_lines(proc.stdout + proc.stderr, 3))})")
                    return rec
                values[var] = m.group(1) if m.groups() else m.group(0)
            env = step_env(copy, values, ctx, chain)
            problem = check_expect(step.get("expect") or {}, proc, copy, env, values)
            if problem:
                label = step.get("name") or short(step["run"], 60)
                rec.update(result="fail", step=i, failure=f"step {i} ({label}): {problem}")
                return rec
        return rec
    except CaseError as e:
        rec.update(result="error", failure=f"bad case file: {e}")
        return rec
    except Exception as e:  # pragma: no cover - runner bug guard
        rec.update(result="error", failure=f"runner error: {type(e).__name__}: {e}")
        return rec
    finally:
        rec["seconds"] = round(time.time() - started, 2)
        if keep:
            rec["copy"] = str(base / "repo")
        else:
            shutil.rmtree(base, ignore_errors=True)


# --------------------------------------------------------------------------- report
def table(results: list[dict]) -> str:
    rows = [("case", "finding", "result", "first failing expectation")]
    for r in results:
        res = r["result"].upper()
        if r["regression"] and r["result"] != "pass":
            res += " (regression!)"
        elif r["regression"]:
            res += " (regression)"
        rows.append((r["name"], r["finding"] or "", res, short(r["failure"] or "", 110)))
    widths = [min(max(len(str(row[i])) for row in rows), cap) for i, cap in enumerate((44, 18, 20, 110))]
    lines = []
    for j, row in enumerate(rows):
        lines.append("  ".join(str(c)[:w].ljust(w) for c, w in zip(row, widths)).rstrip())
        if j == 0:
            lines.append("  ".join("-" * w for w in widths))
    return "\n".join(lines)


def totals(results: list[dict]) -> dict:
    out: dict[str, dict] = {}
    for r in results:
        t = out.setdefault(r["owner"], {"cases": 0, "pass": 0, "fail": 0, "regression_fail": 0})
        t["cases"] += 1
        if r["result"] in ("pass", "skipped"):
            t["pass"] += 1
        else:
            t["fail"] += 1
            if r["regression"]:
                t["regression_fail"] += 1
    return out


def run_cases(cases: list[dict], src_root: Path, cases_dir: Path | None = None, ctx: dict | None = None,
              keep: bool = False, jobs: int | None = None) -> list[dict]:
    """Run conformance cases in parallel, each in a fresh copy of SRC_ROOT; return one record per case."""
    jobs = jobs or min(8, (os.cpu_count() or 2))
    with cf.ThreadPoolExecutor(max_workers=jobs) as pool:
        return list(pool.map(lambda c: run_case(c, src_root, cases_dir, keep, ctx), cases))


def run(reviews: list[str] | None = None, case: str | None = None, as_json: bool = False,
        root: str | None = None, out: str | None = None, cases_dir: str | None = None,
        keep: bool = False, jobs: int | None = None) -> int:
    reviews = reviews or REVIEWS
    bad = [r for r in reviews if r not in REVIEWS]
    if bad:
        print(f"error: unknown review(s) {bad}; choose from {REVIEWS}", file=sys.stderr)
        return 2
    cdir = Path(cases_dir).resolve() if cases_dir else ROOT / "evals" / "framework"
    src_root = Path(root).resolve() if root else ROOT
    cases = load_cases(cdir, reviews, case)
    if not cases:
        print("error: no cases matched", file=sys.stderr)
        return 2
    results = run_cases(cases, src_root, cdir, CORE_CTX, keep, jobs)
    order = {r: i for i, r in enumerate(REVIEWS)}
    results.sort(key=lambda r: (order.get(r["owner"], 9), r["name"] or ""))
    summary = {"generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
               "root": str(src_root), "reviews": reviews, "case_filter": case,
               "totals": totals(results),
               "passed": sum(r["result"] in ("pass", "skipped") for r in results),
               "failed": sum(r["result"] not in ("pass", "skipped") for r in results),
               "cases": results}
    out_path = Path(out) if out else ROOT / "build" / "framework-evals" / "latest.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    if as_json:
        print(json.dumps(summary, indent=2))
    else:
        print(table(results))
        print()
        for r in results:
            if r.get("copy"):
                print(f"kept {r['name']}: {r['copy']}")
        for owner, t in summary["totals"].items():
            extra = f", {t['regression_fail']} regression case(s) failing" if t["regression_fail"] else ""
            print(f"{owner:<14} {t['pass']}/{t['cases']} pass{extra}")
        print(f"\n{summary['passed']} passed, {summary['failed']} failed -> {out_path}")
    return 0 if summary["failed"] == 0 else 1


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="framework_eval", description=__doc__.split("\n")[0])
    p.add_argument("reviews", nargs="*", help=f"which reviews' cases to run: {', '.join(REVIEWS)} (default: all)")
    p.add_argument("--case", help="run only cases whose name matches this glob")
    p.add_argument("--json", action="store_true", help="print the JSON summary instead of the table")
    p.add_argument("--root", help="repo tree to test (default: this repo); cases always come from --cases-dir")
    p.add_argument("--cases-dir", help="folder holding <review>/*.yaml and fixtures/ (default: evals/framework)")
    p.add_argument("--out", help="where to write the JSON summary (default: build/framework-evals/latest.json)")
    p.add_argument("--keep", action="store_true", help="keep each case's temporary copy and print its path")
    p.add_argument("--jobs", type=int, help="cases to run in parallel (default: up to 8)")
    a = p.parse_args(argv)
    return run(a.reviews, a.case, a.json, a.root, a.out, a.cases_dir, a.keep, a.jobs)


if __name__ == "__main__":
    sys.exit(main())

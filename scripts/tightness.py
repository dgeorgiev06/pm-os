#!/usr/bin/env python3
"""tightness — core's lint for component text: principles, skills, modes, agents and the CoS manual.

Everything an agent loads costs tokens on every run, so the lint fails a component that is over its
kind's word budget, a mode SKILL.md that breaks the step structure, a file with too many filler
phrases, and text that copies a principle or another component's paragraph instead of citing it; a
long average sentence is a warning. Settings: `lint:` in pm-os.yaml (DEFAULTS below).

pmos finds the files (`pmos lint`, `pmos validate`, `pmos pack add`, and `forge.py lint` through
`pmos lint DIR`); this module only reads text. A component is a dict:
  {"file": "packs/pm/modes/prd/SKILL.md", "kind": principle|skill|mode|agent|cos|role|manifest|standard,
   "pack": "pm", "id": "pm:testable-requirements" (principles and roles), "text": "..."}
`role` and `manifest` components (roles.yaml personas and rubrics, mode.yaml done lines)
are only checked for copied principles. A `standard` (standards/<name>.yaml) is data: its `text` is
the `contains` and `judgment` lines, with their `labels`; each must be one sentence of at most
`lint.budgets.standard_line` words, with no filler, copying no principle.
"""
from __future__ import annotations

import math
import re

import yaml

DEFAULTS = {
    "budgets": {"principle": 120, "principle_check": 25, "skill": 400, "mode": 450, "agent": 500, "cos": 1000,
                "standard_line": 25},
    "warn_at": 0.9,            # warn at this share of a budget; fail over it
    "max_raise": 1.5,          # a file's `budget:` (with `budget_reason:`) may be at most this times its kind's
    "step_max_words": 60,      # per numbered step of a mode SKILL.md
    "filler_max": {"principle": 0, "default": 2},
    "sentence_avg_max": 22,    # warn above this average sentence length (words)
    "copy_words": 8,           # this many consecutive words of a principle's body or check = a restatement
    "duplicate": {"min_words": 15, "shingle": 4, "similarity": 0.6},
    "filler": ["it is important to", "it's important to", "make sure to", "be sure to", "in order to",
               "please note", "note that", "robust", "seamless", "comprehensive", "leverage", "delve",
               "various", "etc.", "should probably", "feel free to", "as needed", "in a timely manner",
               "very", "really", "basically"],
}
BUDGETED = ("principle", "skill", "mode", "agent", "cos")
TAG = re.compile(r"\[(model|candidate-code|code:[^\]]*)\]")
STEP = re.compile(r"^(\d+)\.\s+(.*)$")
FENCE = re.compile(r"^\s*(```|~~~)")
INLINE = re.compile(r"`[^`]*`")
HAS_WORD = re.compile(r"[A-Za-z0-9]")
NORM = re.compile(r"[a-z0-9]+")


def settings(cfg: dict | None) -> dict:
    """DEFAULTS with pm-os.yaml `lint:` merged over them (one level deep for dicts)."""
    out = {k: (dict(v) if isinstance(v, dict) else v) for k, v in DEFAULTS.items()}
    for k, v in ((cfg or {}).get("lint") or {}).items():
        out[k] = {**out[k], **v} if isinstance(out.get(k), dict) and isinstance(v, dict) else v
    return out


# --------------------------------------------------------------------------- text
def split_frontmatter(text: str) -> tuple[dict, list[str], int]:
    """(frontmatter, body lines, line number of the first body line)."""
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n?", text, flags=re.S)
    if not m:
        return {}, text.splitlines(), 1
    try:
        meta = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        meta = {}
    return (meta if isinstance(meta, dict) else {}), text[m.end():].splitlines(), m.group(0).count("\n") + 1


def mask_code(lines: list[str]) -> list[str]:
    """Fenced code blocks blanked out, line numbers kept."""
    out, fenced = [], False
    for line in lines:
        if FENCE.match(line):
            fenced = not fenced
            out.append("")
        else:
            out.append("" if fenced else line)
    return out


def count_words(text: str) -> int:
    return sum(1 for tok in text.split() if HAS_WORD.search(tok))


def norm(text: str) -> list[str]:
    return NORM.findall(INLINE.sub(lambda m: m.group(0)[1:-1], text).lower().replace("’", "'"))


def prose(line: str) -> str:
    """A line without inline code (filler and sentence checks read prose only)."""
    return INLINE.sub("x", line)


def prose_words(text: str) -> list[str]:
    """Normalised words outside inline code: the duplicate-paragraph check compares prose, since every
    mode runs the same commands."""
    return norm(INLINE.sub(" ", text))


def paragraphs(lines: list[str], first: int) -> list[tuple[int, str]]:
    out, cur, start = [], [], 0
    for i, line in enumerate(lines + [""]):
        if line.strip() and not line.lstrip().startswith("#"):
            if not cur:
                start = first + i
            cur.append(line.strip())
        elif cur:
            out.append((start, " ".join(cur)))
            cur = []
    return out


def sentence_lengths(lines: list[str]) -> list[int]:
    """Words per sentence: list items and table-free paragraphs, split at . ! ? before a capital."""
    out = []
    for _n, para in paragraphs([ln for ln in lines if not ln.lstrip().startswith("|")], 1):
        items = re.split(r"\s(?=(?:[-*]|\d+\.)\s)", prose(para))
        for item in items:
            for s in re.split(r"(?<=[.!?])\s+(?=[A-Z(\"'*\[])", item):
                n = count_words(s)
                if n:
                    out.append(n)
    return out


def steps(lines: list[str], first: int) -> list[dict]:
    """A mode's numbered steps: {n, line, text}; a step runs to the next step, a heading, or a paragraph
    that isn't indented."""
    out, cur, blank = [], None, False
    for i, line in enumerate(lines):
        m = STEP.match(line)
        if m:
            cur = {"n": int(m.group(1)), "line": first + i, "text": m.group(2)}
            out.append(cur)
        elif not line.strip():
            blank = True
            continue
        elif line.lstrip().startswith("#") or (blank and not line[:1].isspace()):
            cur = None
        elif cur is not None:
            cur["text"] += " " + line.strip()
        blank = False
    return out


def filler_patterns(entries: list[str]) -> list[tuple[str, re.Pattern]]:
    """`/regex/` entries are regexes; anything else is a phrase matched as whole words, any case."""
    out = []
    for e in entries or []:
        e = str(e)
        if len(e) > 2 and e.startswith("/") and e.endswith("/"):
            out.append((e[1:-1].replace("\\b", ""), re.compile(e[1:-1], re.I)))
            continue
        phrase = e.strip()
        rx = re.escape(phrase)
        rx = (r"(?<![\w-])" if phrase[:1].isalnum() else "") + rx + (r"(?![\w-])" if phrase[-1:].isalnum() else "")
        out.append((phrase.lower(), re.compile(rx, re.I)))
    return out


def shingles(words: list[str], n: int) -> set[tuple[str, ...]]:
    return {tuple(words[i:i + n]) for i in range(len(words) - n + 1)}


# --------------------------------------------------------------------------- the lint
def lint(targets: list[dict], context: list[dict], cfg: dict | None = None, cos_files: list[str] | None = None) -> dict:
    """Lint TARGETS (components); CONTEXT (all installed components, targets included) supplies the
    principles and paragraphs that cross-file checks compare against. COS_FILES: the files that make up
    the CoS manual (the cos pack's COS.md and each installed cos_section), whose words are summed."""
    s = settings(cfg)
    budgets, files, notes = s["budgets"], [], []
    fill = filler_patterns(s["filler"])
    fmax = s["filler_max"] if isinstance(s["filler_max"], dict) else {"default": s["filler_max"]}
    parsed = {c["file"]: _parse(c) for c in context + [t for t in targets if t not in context]}

    principles = []      # (id, file, shingles) for copied-principle checks
    for c in context:
        if c["kind"] == "principle":
            meta, lines, _ = parsed[c["file"]][:3]
            words = norm(" ".join(lines)) + ["⁣"] + norm(str(meta.get("check") or ""))
            principles.append((c.get("id") or c["file"], c["file"], shingles(words, s["copy_words"])))
    dup = s["duplicate"]
    paras = []           # (file, line, words, shingles) for near-duplicate checks
    for c in context:
        if c["kind"] in BUDGETED:
            _meta, lines, first, masked = parsed[c["file"]]
            for line_no, text in paragraphs(masked, first):
                w = prose_words(text)
                if len(w) >= dup["min_words"]:
                    paras.append((c["file"], line_no, shingles(w, dup["shingle"])))

    for c in targets:
        meta, lines, first, masked = parsed[c["file"]]
        rec = {"file": c["file"], "kind": c["kind"], "pack": c.get("pack"), "words": None, "budget": None,
               "budget_source": None, "filler": 0, "filler_max": None, "sentence_avg": None, "steps": None,
               "errors": [], "warnings": [], "notes": []}
        err, warn = rec["errors"].append, rec["warnings"].append
        if c["kind"] in BUDGETED:
            words = count_words("\n".join(masked))
            budget, source = _budget(c, meta, budgets, s, err)
            rec.update(words=words, budget=budget, budget_source=source)
            _check_budget(c["file"], "", words, budget, source, s["warn_at"], err, warn)
            if c["kind"] == "principle":
                cw = count_words(str(meta.get("check") or ""))
                _check_budget(c["file"], "check is ", cw, budgets["principle_check"], "lint.budgets.principle_check",
                              s["warn_at"], err, warn, unit="words")
            if c["kind"] == "mode":
                rec["steps"] = _check_steps(c["file"], masked, first, s["step_max_words"], err)
            hits = []
            for i, line in enumerate(masked):
                for label, rx in fill:
                    hits += [(first + i, label) for _ in rx.finditer(prose(line))]
            limit = int(fmax.get(c["kind"], fmax.get("default", 2)))
            rec.update(filler=len(hits), filler_max=limit)
            rec["notes"] += [f"{c['file']}:{n}: filler '{label}'" for n, label in hits]
            if len(hits) > limit:
                err(f"{c['file']}: {len(hits)} filler phrase(s), over lint.filler_max ({limit})")
            lengths = sentence_lengths(masked)
            if lengths:
                avg = sum(lengths) / len(lengths)
                rec["sentence_avg"] = round(avg, 1)
                if avg > s["sentence_avg_max"]:
                    warn(f"{c['file']}: average sentence is {math.ceil(avg)} words (lint.sentence_avg_max "
                         f"{s['sentence_avg_max']})")
            for line_no, text in paragraphs(masked, first):
                w = prose_words(text)
                if len(w) < dup["min_words"]:
                    continue
                mine = shingles(w, dup["shingle"])
                for f2, l2, theirs in paras:
                    if f2 == c["file"]:
                        continue
                    sim = len(mine & theirs) / len(mine | theirs)
                    if sim >= dup["similarity"]:
                        err(f"{c['file']}:{line_no}: paragraph is a near-duplicate of {f2}:{l2} ({sim:.0%} similar); "
                            f"keep it in one place and point to it")
                        break
        if c["kind"] == "standard":
            _check_standard_lines(c, int(budgets.get("standard_line", 25)), fill, err)
        if c["kind"] != "principle":
            _check_copies(c, masked if c["kind"] in BUDGETED else None, first, principles, s["copy_words"], err)
        if c["kind"] in BUDGETED:
            files.append(rec)
        elif rec["errors"]:
            files.append(rec)
        notes += rec["notes"]

    manual = None
    if cos_files:
        by_file = {c["file"]: c for c in context + targets}
        words = sum(count_words("\n".join(parsed[f][3])) for f in cos_files if f in by_file)
        budget = budgets["cos"]
        manual = {"files": cos_files, "words": words, "budget": budget, "errors": [], "warnings": []}
        name = "CoS manual (" + " + ".join(cos_files) + ")"
        _check_budget(name, "", words, budget, "lint.budgets.cos", s["warn_at"], manual["errors"].append,
                      manual["warnings"].append)
        if not any(t["kind"] == "cos" and t["file"] in cos_files for t in targets):
            manual["errors"], manual["warnings"] = [], []   # reported only when a manual file is linted
    errors = [e for f in files for e in f["errors"]] + (manual["errors"] if manual else [])
    warnings = [w for f in files for w in f["warnings"]] + (manual["warnings"] if manual else [])
    return {"contract": "lint@1", "files": files, "manual": manual, "errors": len(errors), "warnings": len(warnings),
            "error_lines": errors, "warning_lines": warnings, "notes": notes}


def _check_standard_lines(c: dict, max_words: int, fill, err) -> None:
    """Each contains/judgment line of a standard: one sentence, at most MAX_WORDS words, no filler."""
    for label, line in zip(c.get("labels") or [], c["text"]):
        where = f"{c['file']}: {label}"
        n = count_words(line)
        if n > max_words:
            err(f"{where}: {n} words, over lint.budgets.standard_line ({max_words}); one short sentence")
        if len(re.split(r"(?<=[.!?])\s+(?=[A-Z0-9(\"'*\[])", prose(line).strip())) > 1:
            err(f"{where}: more than one sentence; a standard's line is one sentence")
        for phrase, rx in fill:
            if rx.search(prose(line)):
                err(f"{where}: filler '{phrase}'")


def _parse(c: dict) -> tuple[dict, list[str], int, list[str]]:
    if c["kind"] in ("role", "manifest", "standard"):
        lines = [str(x) for x in c["text"]] if isinstance(c["text"], list) else str(c["text"]).splitlines()
        return {}, lines, 1, lines
    meta, lines, first = split_frontmatter(c["text"])
    return meta, lines, first, mask_code(lines)


def _budget(c: dict, meta: dict, budgets: dict, s: dict, err) -> tuple[int, str]:
    base = int(budgets[c["kind"]])
    declared = meta.get("budget")
    if declared is None:
        return base, f"lint.budgets.{c['kind']}"
    if not isinstance(declared, int) or declared <= 0:
        err(f"{c['file']}: budget must be a positive whole number of words (got {declared!r})")
        return base, f"lint.budgets.{c['kind']}"
    if not str(meta.get("budget_reason") or "").strip():
        err(f"{c['file']}: budget {declared} needs a budget_reason saying why this file needs more words")
        return base, f"lint.budgets.{c['kind']}"
    cap = int(base * float(s["max_raise"]))
    if declared > cap:
        err(f"{c['file']}: budget {declared} is over {s['max_raise']}x the {c['kind']} budget ({cap} max)")
        return base, f"lint.budgets.{c['kind']}"
    return declared, "budget: in frontmatter"


def _check_budget(name, prefix, words, budget, source, warn_at, err, warn, unit="words") -> None:
    label = source.split(".")[-1] if source.startswith("lint.") else "its own"
    where = f"({label}; {source})" if source.startswith("lint.") else f"({source})"
    if words > budget:
        err(f"{name}: {prefix}{words} {unit}, over its budget of {budget} {where}")
    elif words >= warn_at * budget:
        warn(f"{name}: {prefix}{words} {unit}, {words / budget:.0%} of its budget of {budget} {where}")


def _check_steps(file: str, masked: list[str], first: int, max_words: int, err) -> int:
    found = steps(masked, first)
    if not found:
        err(f"{file}: no numbered steps; a mode's SKILL.md is numbered steps, each tagged [model], "
            f"[code: …] or [candidate-code]")
        return 0
    for st in found:
        if not TAG.search(st["text"]):
            err(f"{file}:{st['line']}: step {st['n']} has no tag ([model], [code: …] or [candidate-code])")
        n = count_words(st["text"])
        if n > max_words:
            err(f"{file}:{st['line']}: step {st['n']} is {n} words, over lint.step_max_words ({max_words})")
    if not re.search(r"pmos(\.py)? task show", found[0]["text"]):
        err(f"{file}: the first step must run `pmos task show`")
    if not re.search(r"pmos(\.py)? task result", found[-1]["text"]):
        err(f"{file}: the last step must run `pmos task result`")
    return len(found)


def _check_copies(c: dict, masked: list[str] | None, first: int, principles, n: int, err) -> None:
    if c["kind"] in ("role", "manifest", "standard"):
        units = [(None, str(t)) for t in (c["text"] if isinstance(c["text"], list) else [c["text"]])]
    else:
        units = paragraphs(masked or [], first)
    reported = set()
    for line_no, text in units:
        mine = shingles(norm(text), n)
        for pid, pfile, theirs in principles:
            if pfile == c["file"] or pid in reported:
                continue
            common = mine & theirs
            if common:
                reported.add(pid)
                quote = " ".join(sorted(common)[0])
                where = f"{c['file']}:{line_no}" if line_no else c["file"]
                who = f" {c['kind']} {c['id']}" if c.get("id") and c["kind"] in ("role", "manifest", "standard") else ""
                err(f"{where}:{who} restates principle {pid} ('{quote} …'); cite the principle instead")


def table(report: dict) -> str:
    """The text table `pmos lint` prints: file, kind, words/budget, filler hits/limit, result."""
    rows = [("file", "kind", "words/budget", "filler", "result")]
    for f in report["files"]:
        if f["words"] is None:
            rows.append((f["file"], f["kind"], "-", "-", "FAIL" if f["errors"] else "ok"))
            continue
        res = "FAIL" if f["errors"] else ("warn" if f["warnings"] else "ok")
        rows.append((f["file"], f["kind"], f"{f['words']}/{f['budget']}", f"{f['filler']}/{f['filler_max']}", res))
    m = report.get("manual")
    if m:
        res = "FAIL" if m["errors"] else ("warn" if m["warnings"] else "ok")
        rows.append(("CoS manual (" + " + ".join(m["files"]) + ")", "cos", f"{m['words']}/{m['budget']}", "-", res))
    widths = [max(len(r[i]) for r in rows) for i in range(5)]
    return "\n".join("  ".join(cell.ljust(w) for cell, w in zip(r, widths)).rstrip() for r in rows)

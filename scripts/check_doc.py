#!/usr/bin/env python3
"""check_doc — check a document against a document standard (pm-os/standard@1).

Usage: python scripts/check_doc.py --standard REF|FILE.yaml DOC [--json]

REF is an installed pack's standard, <pack>:standards/<name> (e.g. pm:standards/prd); FILE.yaml is a
standard file. A mode that declares `standard:` gets this as its done.must code line `standard`.

A section is the first heading (any level) that contains its title or an alias, in any case; it runs
to the next heading of the same or a higher level, so subsections belong to it. Rules, each named in
the output: section:<id> (a required section is missing), numbered:<id> (<prefix>1, <prefix>2, … with
no gaps), fields:<id> (a table naming each field), min_items:<id> (list items plus table rows) and
forbid:<id> (a pattern found anywhere).

Exit 0 = pass. Exit 1 = fail (prints `- <rule>: <message>` per problem; a missing DOC fails too).
Exit 2 = usage, an invalid standard or an unknown ref.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pmos  # noqa: E402

HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
FENCE = re.compile(r"^\s*(```|~~~)")
ITEM = re.compile(r"^\s*([-*+]|\d+[.)])\s+\S")
TABLE_RULE = re.compile(r":?-{2,}:?")      # a |---|:--:| separator cell


def load(ref: str) -> tuple[str, dict]:
    """(the name to print, the standard) for REF, a qualified ref or a standard file."""
    path = Path(ref)
    if path.suffix in (".yaml", ".yml") and path.is_file():
        data, shown = pmos.load_yaml(path), pmos.rel(path)
    else:
        known = pmos.all_standards()
        if ref not in known:
            raise LookupError(f"unknown standard '{ref}'; known: {', '.join(sorted(known)) or 'none'} "
                              f"(or pass a standard file)")
        data, shown = pmos.load_yaml(known[ref]), ref
    errs = pmos.schema_errors(data, "standard", shown)
    if errs:
        raise ValueError("does not match contracts/standard.schema.json:\n  - " + "\n  - ".join(errs))
    return shown, data


def headings(lines: list[str]) -> list[tuple[int, int, str]]:
    """(line index, level, text) of every heading outside fenced code."""
    out, fenced = [], False
    for i, line in enumerate(lines):
        if FENCE.match(line):
            fenced = not fenced
            continue
        m = HEADING.match(line) if not fenced else None
        if m:
            out.append((i, len(m.group(1)), m.group(2)))
    return out


def find_section(section: dict, lines: list[str], heads: list[tuple[int, int, str]]) -> tuple[int, list[str]] | None:
    """(heading line index, body lines) of the first heading naming SECTION, or None."""
    names = [section["title"].lower(), *[a.lower() for a in section.get("aliases") or []]]
    for n, (i, level, text) in enumerate(heads):
        if any(name in text.lower() for name in names):
            end = next((j for j, lv, _ in heads[n + 1:] if lv <= level), len(lines))
            return i, lines[i + 1:end]
    return None


def tables(body: list[str]) -> list[list[list[str]]]:
    """Markdown tables in BODY as rows of cells (the header first, the |---| rule dropped)."""
    out, cur = [], []
    for line in body + [""]:
        if line.strip().startswith("|"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if not all(TABLE_RULE.fullmatch(c) for c in cells):
                cur.append(cells)
        elif cur:
            out.append(cur)
            cur = []
    return out


def check(std: dict, text: str) -> list[dict]:
    lines = text.splitlines()
    heads = headings(lines)
    problems = []

    def problem(rule: str, section: str | None, message: str, line: int | None = None) -> None:
        problems.append({"rule": rule, "section": section, "message": message, "line": line})

    for s in std["sections"]:
        found = find_section(s, lines, heads)
        if found is None:
            if s["required"]:
                accepted = ", ".join([s["title"], *(s.get("aliases") or [])])
                problem(f"section:{s['id']}", s["id"], f'missing section "{s["title"]}" (a heading naming: {accepted})')
            continue
        at, body = found
        joined = "\n".join(body)
        if s.get("numbered"):
            prefix = s["numbered"]["prefix"]
            nums = sorted({int(n) for n in re.findall(rf"\b{re.escape(prefix)}(\d+)\b", joined)})
            if 1 not in nums:
                problem(f"numbered:{s['id']}", s["id"], f"items are not numbered (expected {prefix}1, {prefix}2, …)", at + 1)
            elif s["numbered"].get("contiguous", True) and nums != list(range(1, nums[-1] + 1)):
                missing = [f"{prefix}{n}" for n in range(1, nums[-1] + 1) if n not in nums]
                problem(f"numbered:{s['id']}", s["id"], f"numbers have gaps (missing {', '.join(missing)})", at + 1)
        found_tables = tables(body)
        if s.get("fields"):
            def named(table, field):
                return any(field.lower() in cell.lower() for cell in table[0])
            best = max(found_tables, key=lambda tb: sum(named(tb, f) for f in s["fields"]), default=None)
            lacking = [f for f in s["fields"] if not (best and named(best, f))]
            if lacking:
                problem(f"fields:{s['id']}", s["id"],
                        (f"the table has no column for {', '.join(lacking)}" if best else "no table")
                        + f" (columns wanted: {', '.join(s['fields'])})", at + 1)
        if s.get("min_items"):
            n = sum(1 for ln in body if ITEM.match(ln)) + sum(len(tb) - 1 for tb in found_tables)
            if n < s["min_items"]:
                problem(f"min_items:{s['id']}", s["id"], f"{n} item(s), at least {s['min_items']} wanted", at + 1)
    for rule in std.get("forbid") or []:
        rx = re.compile(rule["pattern"])
        for i, line in enumerate(lines, 1):
            m = rx.search(line)
            if m:
                problem(f"forbid:{rule['id']}", None, f"{rule['message']}: '{m.group(0)}' (line {i})", i)
    return problems


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--standard", required=True, help="<pack>:standards/<name> of an installed pack, or a standard file")
    p.add_argument("doc", help="the document to check (Markdown)")
    p.add_argument("--json", action="store_true", help="print check-doc@1 JSON")
    a = p.parse_args()
    try:
        shown, std = load(a.standard)
    except (LookupError, ValueError, pmos.PmosError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    doc = Path(a.doc)
    if not doc.is_file():
        print(f"FAIL {shown} {a.doc}\n- not found: {a.doc}")
        return 1
    problems = check(std, doc.read_text(encoding="utf-8"))
    if a.json:
        print(json.dumps({"contract": "check-doc@1", "standard": shown, "file": a.doc, "pass": not problems,
                          "problems": problems}, indent=2, ensure_ascii=False))
    else:
        print(f"{'FAIL' if problems else 'PASS'} {shown} {a.doc}")
        for pr in problems:
            print(f"- {pr['rule']}: {pr['message']}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())

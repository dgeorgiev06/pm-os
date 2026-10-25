"""Deterministic PRD checks (a codified step of pm/prd).

Usage: python packs/pm/modes/prd/scripts/check_prd.py outputs/<id>/prd.md
Exit 0 = pass. Exit 1 = prints what to fix.
"""
import re
import sys
from pathlib import Path

REQUIRED_SECTIONS = [
    "problem",
    "personas",
    "requirements",
    "success metrics",
    "open questions",
]


def check(text: str) -> list[str]:
    problems = []
    headings = [h.strip().lower() for h in re.findall(r"^#{1,3}\s+(.+)$", text, flags=re.M)]
    for section in REQUIRED_SECTIONS:
        if not any(section in h for h in headings):
            problems.append(f"missing section: '{section}'")
    if not re.search(r"\bR1\b", text):
        problems.append("requirements are not numbered (expected R1, R2, ...)")
    numbers = [int(n) for n in re.findall(r"\bR(\d+)\b", text)]
    if numbers and sorted(set(numbers)) != list(range(1, max(numbers) + 1)):
        problems.append("requirement numbers have gaps")
    if re.search(r"\b(TODO|TBD|XXX)\b", text):
        problems.append("unresolved TODO/TBD/XXX markers")
    return problems


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    path = Path(sys.argv[1])
    if not path.exists():
        print(f"not found: {path}")
        return 1
    problems = check(path.read_text(encoding="utf-8"))
    if problems:
        print("FAIL")
        for p in problems:
            print(f"- {p}")
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())

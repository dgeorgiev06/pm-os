"""Group closed tickets into release-note sections (a codified step of pm/release-notes).

Usage: python packs/pm/modes/release-notes/scripts/group_tickets.py closed.json [--audience customers|internal]
Input:  [{"key": "STK-401", "summary": "...", "type": "Story|Task|Bug|Spike", "labels": [...]}, ...]
Output: JSON on stdout: {"audience", "sections": {"new": [...], "improved": [...], "fixed": [...],
        "internal": [...]}, "dropped": [...]} — "internal" and "dropped" are omitted/filled by audience.
"""
import argparse
import json
import sys

INTERNAL_LABELS = {"internal", "tech-debt", "refactor", "tooling", "ci", "spike"}


def section_for(ticket: dict) -> str:
    kind = (ticket.get("type") or "").lower()
    labels = {l.lower() for l in ticket.get("labels") or []}
    if kind == "spike" or labels & INTERNAL_LABELS:
        return "internal"
    if kind == "bug":
        return "fixed"
    if kind == "story":
        return "new"
    return "improved"


def group(tickets: list[dict], audience: str = "customers") -> dict:
    sections = {"new": [], "improved": [], "fixed": [], "internal": []}
    for t in sorted(tickets, key=lambda t: t["key"]):
        sections[section_for(t)].append({"key": t["key"], "summary": t["summary"]})
    dropped = []
    if audience == "customers":
        dropped = sections.pop("internal")
    return {"audience": audience, "sections": sections, "dropped": dropped,
            "counts": {k: len(v) for k, v in sections.items()}}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("closed")
    p.add_argument("--audience", choices=["customers", "internal"], default="customers")
    args = p.parse_args()
    with open(args.closed, encoding="utf-8") as f:
        tickets = json.load(f)
    print(json.dumps(group(tickets, args.audience), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

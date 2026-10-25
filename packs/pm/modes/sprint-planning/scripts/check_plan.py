"""Check a sprint plan against capacity (a codified step of pm/sprint-planning: plan-to-capacity).

Usage: python packs/pm/modes/sprint-planning/scripts/check_plan.py plan.json capacity.json
Input:  plan.json      {"committed": [{"summary": ..., "points": 8}, ...], "stretch": [...]}
        capacity.json  the output of capacity.py ({"committed_points": 21, "stretch_points": 3, ...})
Output: JSON on stdout with the totals; exit 1 with "over capacity" (or a missing estimate) when the
        plan doesn't fit, so it is caught before any Reviewer is spent.
"""
import json
import sys


def check(plan: dict, cap: dict) -> tuple[dict, list[str]]:
    problems = []
    totals = {}
    for group in ("committed", "stretch"):
        items = plan.get(group) or []
        unestimated = [i.get("summary") or i.get("key") or "?" for i in items
                       if not isinstance(i.get("points"), (int, float)) or isinstance(i.get("points"), bool)]
        if unestimated:
            problems.append(f"{group} item(s) without numeric points: {', '.join(map(str, unestimated))}")
        totals[group] = sum(i["points"] for i in items if isinstance(i.get("points"), (int, float)))
    limit = cap.get("committed_points")
    if not isinstance(limit, (int, float)):
        problems.append("capacity.json has no numeric committed_points (run capacity.py)")
    elif totals["committed"] > limit:
        problems.append(f"over capacity: {totals['committed']} committed points > committed_points {limit}")
    stretch_limit = cap.get("stretch_points")
    if isinstance(stretch_limit, (int, float)) and totals["stretch"] > stretch_limit:
        problems.append(f"stretch over capacity: {totals['stretch']} points > stretch_points {stretch_limit}")
    report = {"committed_points": totals["committed"], "capacity": limit,
              "stretch_points": totals["stretch"], "stretch_capacity": stretch_limit, "ok": not problems}
    return report, problems


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    with open(sys.argv[1], encoding="utf-8") as f:
        plan = json.load(f)
    with open(sys.argv[2], encoding="utf-8") as f:
        cap = json.load(f)
    report, problems = check(plan, cap)
    print(json.dumps(report, indent=2))
    for p in problems:
        print(f"error: {p}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())

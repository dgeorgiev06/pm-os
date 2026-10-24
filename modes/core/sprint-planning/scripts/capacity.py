"""Sprint capacity from recent velocity (a codified step of core/sprint-planning).

Usage: python modes/core/sprint-planning/scripts/capacity.py velocity.json
Input:  {"velocities": [31, 28, 34], "availability": 0.9, "buffer": 0.15}
        availability = share of normal team capacity this sprint (holidays, on-call)
        buffer       = share held back for unplanned work (default 0.15)
Output: JSON on stdout with average velocity, raw capacity and committed points.
"""
import json
import sys
from statistics import mean


def capacity(velocities: list[float], availability: float = 1.0, buffer: float = 0.15) -> dict:
    if not velocities:
        raise ValueError("need at least one past velocity")
    if not 0 < availability <= 1:
        raise ValueError("availability must be in (0, 1]")
    if not 0 <= buffer < 1:
        raise ValueError("buffer must be in [0, 1)")
    recent = velocities[-3:]
    avg = mean(recent)
    raw = avg * availability
    committed = int(raw * (1 - buffer))
    return {
        "velocities_used": recent,
        "average_velocity": round(avg, 1),
        "availability": availability,
        "buffer": buffer,
        "raw_capacity": round(raw, 1),
        "committed_points": committed,
        "stretch_points": int(raw) - committed,
    }


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    with open(sys.argv[1], encoding="utf-8") as f:
        data = json.load(f)
    result = capacity(
        data["velocities"],
        data.get("availability", 1.0),
        data.get("buffer", 0.15),
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

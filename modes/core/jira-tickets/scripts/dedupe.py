"""Flag drafted tickets that likely duplicate existing ones (a codified step of core/jira-tickets).

Usage: python modes/core/jira-tickets/scripts/dedupe.py drafts.json existing.json [--threshold 0.6]
drafts.json:   [{"summary": "..."}, ...]
existing.json: [{"key": "STK-1", "summary": "...", "status": "..."}, ...]
Prints JSON: [{"draft_index": i, "draft": "...", "match": "STK-1", "existing": "...", "score": 0.82}, ...]
"""
import argparse
import json
import re
import sys
from difflib import SequenceMatcher

STOP = {"a", "an", "the", "for", "to", "of", "and", "in", "on", "with", "via", "through"}


def normalize(text: str) -> str:
    words = re.findall(r"[a-z0-9]+", text.lower())
    return " ".join(w for w in words if w not in STOP)


def similarity(a: str, b: str) -> float:
    na, nb = normalize(a), normalize(b)
    if not na or not nb:
        return 0.0
    seq = SequenceMatcher(None, na, nb).ratio()
    sa, sb = set(na.split()), set(nb.split())
    jaccard = len(sa & sb) / len(sa | sb)
    return round(max(seq, jaccard), 3)


def find_duplicates(drafts: list[dict], existing: list[dict], threshold: float) -> list[dict]:
    found = []
    for i, draft in enumerate(drafts):
        best, best_score = None, 0.0
        for item in existing:
            score = similarity(draft["summary"], item["summary"])
            if score > best_score:
                best, best_score = item, score
        if best and best_score >= threshold:
            found.append({
                "draft_index": i,
                "draft": draft["summary"],
                "match": best["key"],
                "existing": best["summary"],
                "score": best_score,
            })
    return found


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("drafts")
    p.add_argument("existing")
    p.add_argument("--threshold", type=float, default=0.6)
    args = p.parse_args()
    with open(args.drafts, encoding="utf-8") as f:
        drafts = json.load(f)
    with open(args.existing, encoding="utf-8") as f:
        existing = json.load(f)
    print(json.dumps(find_duplicates(drafts, existing, args.threshold), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

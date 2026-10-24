#!/usr/bin/env python3
"""todos — the PM's todo list, kept in context/todos.yaml. Deterministic; no model.

The CoS runs this directly when the PM says exactly what to change ("add X due Tuesday",
"done td-3"): the PM's words are the approval. Changes proposed by an agent arrive as a diff and
are applied by the Operator with `apply`, after the PM approves.

  add TITLE [--due YYYY-MM-DD] [--estimate H] [--priority 1|2|3] [--notes TEXT]
  list [--all] [--json]                   open items, due date first; shows what's waiting on the PM
  edit ID [--title] [--due] [--estimate] [--priority] [--notes]
  done ID [--note TEXT]
  drop ID [--note TEXT]                   closes without doing it (never deletes)
  link ID TASK --mode PACK/MODE [--instructions TEXT] [--review-h H]
                                          record a delegation the PM directed
  sync                                    update delegated todos from their pmos tasks
  plan [--days N] [--start YYYY-MM-DD] [--hours JSON] [--default-hours H] [--weekends] [--json]
                                          fit open todos into free hours, due date first
  apply DIFF.json                         apply an approved diff (Operator only)

Files: PMOS_TODOS_FILE overrides context/todos.yaml; PMOS_STATE_DIR overrides state/.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
OPEN = ("open", "delegated", "blocked")
WAITING_ON_PM = {"awaiting_approval", "blocked"}


class TodoError(Exception):
    pass


def todos_file() -> Path:
    return Path(os.environ.get("PMOS_TODOS_FILE") or ROOT / "context" / "todos.yaml")


def tasks_dir() -> Path:
    return Path(os.environ.get("PMOS_STATE_DIR") or ROOT / "state") / "tasks"


def today() -> str:
    return dt.date.today().isoformat()


def load() -> list[dict]:
    f = todos_file()
    if not f.exists():
        return []
    return list((yaml.safe_load(f.read_text(encoding="utf-8")) or {}).get("todos") or [])


def save(items: list[dict]) -> None:
    f = todos_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    header = ("# The PM's todo list. Managed by packs/cos/scripts/todos.py; personal, so not committed.\n"
              "# status: open | delegated | blocked | done | dropped · owner: me | agent\n")
    tmp = f.with_suffix(".tmp")
    tmp.write_text(header + yaml.safe_dump({"todos": items}, sort_keys=False, allow_unicode=True), encoding="utf-8")
    os.replace(tmp, f)


def find(items: list[dict], todo_id: str) -> dict:
    for t in items:
        if t["id"] == todo_id:
            return t
    raise TodoError(f"no todo {todo_id}")


def check_date(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        return dt.date.fromisoformat(value).isoformat()
    except ValueError:
        raise TodoError(f"'{value}' is not a date (use YYYY-MM-DD)")


def next_id(items: list[dict]) -> str:
    nums = [int(t["id"].split("-")[1]) for t in items if t.get("id", "").startswith("td-")]
    return f"td-{(max(nums) + 1) if nums else 1}"


def new_item(items: list[dict], title: str, due=None, estimate=None, priority=None, notes=None) -> dict:
    if not title or not title.strip():
        raise TodoError("a todo needs a title")
    item = {"id": next_id(items), "title": title.strip(), "status": "open", "owner": "me",
            "due": check_date(due), "estimate_h": float(estimate) if estimate is not None else None,
            "priority": int(priority) if priority is not None else 2, "notes": notes, "created": today()}
    if item["priority"] not in (1, 2, 3):
        raise TodoError("priority is 1 (low), 2 (normal) or 3 (high)")
    return {k: v for k, v in item.items() if v is not None}


def task_state(task_id: str) -> str | None:
    p = tasks_dir() / f"{task_id}.json"
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8")).get("state")


def sort_key(t: dict):
    return (t.get("due") or "9999-12-31", -int(t.get("priority", 2)), t["id"])


# --------------------------------------------------------------------------- commands
def cmd_add(a) -> int:
    items = load()
    item = new_item(items, a.title, a.due, a.estimate, a.priority, a.notes)
    items.append(item)
    save(items)
    print(f"{item['id']} added: {item['title']}" + (f" (due {item['due']})" if item.get("due") else ""))
    return 0


def cmd_list(a) -> int:
    items = sorted(load(), key=sort_key)
    if not a.all:
        items = [t for t in items if t["status"] in OPEN]
    for t in items:
        if t.get("task"):
            t["task_state"] = task_state(t["task"])
    if a.json:
        print(json.dumps(items, indent=2))
        return 0
    if not items:
        print("(no open todos)")
    for t in items:
        bits = [t["id"], f"[{t['status']}]", t["title"]]
        if t.get("due"):
            bits.append(f"due {t['due']}")
        if t.get("estimate_h"):
            bits.append(f"{t['estimate_h']}h")
        if t.get("task"):
            bits.append(f"→ {t['mode']} {t['task']} ({t.get('task_state') or 'unknown'})")
            if t.get("task_state") in WAITING_ON_PM:
                bits.append("WAITING ON YOU")
        print("  ".join(bits))
    return 0


def cmd_edit(a) -> int:
    items = load()
    t = find(items, a.id)
    if a.title:
        t["title"] = a.title
    if a.due:
        t["due"] = check_date(a.due)
    if a.estimate is not None:
        t["estimate_h"] = float(a.estimate)
    if a.priority is not None:
        if a.priority not in (1, 2, 3):
            raise TodoError("priority is 1, 2 or 3")
        t["priority"] = a.priority
    if a.notes is not None:
        t["notes"] = a.notes
    save(items)
    print(f"{a.id} updated")
    return 0


def close(a, status: str) -> int:
    items = load()
    t = find(items, a.id)
    if t["status"] in ("done", "dropped"):
        raise TodoError(f"{a.id} is already {t['status']}")
    t["status"], t["closed"] = status, today()
    if a.note:
        t["notes"] = (t.get("notes", "") + " · " if t.get("notes") else "") + a.note
    save(items)
    print(f"{a.id} {status}: {t['title']}")
    return 0


def cmd_link(a) -> int:
    items = load()
    t = find(items, a.id)
    if t["status"] not in ("open", "blocked"):
        raise TodoError(f"{a.id} is {t['status']}; only open or blocked todos can be delegated")
    if task_state(a.task) is None:
        raise TodoError(f"no pmos task {a.task}; create it with `pmos task new … --todo {a.id}` first")
    t.update({"status": "delegated", "owner": "agent", "task": a.task, "mode": a.mode,
              "review_h": a.review_h, "delegated": today()})
    if a.instructions:
        t["instructions"] = a.instructions
    save(items)
    print(f"{a.id} delegated to {a.mode} as {a.task}")
    return 0


def sync_items(items: list[dict]) -> list[str]:
    changes = []
    for t in items:
        if t["status"] not in ("delegated", "blocked") or not t.get("task"):
            continue
        state = task_state(t["task"])
        if state == "done" and t["status"] != "done":
            t["status"], t["closed"] = "done", today()
            changes.append(f"{t['id']} done via {t['task']}")
        elif state == "failed" and t["status"] != "blocked":
            t["status"] = "blocked"
            changes.append(f"{t['id']} blocked: {t['task']} failed; it's yours again or re-delegate")
    return changes


def cmd_sync(_a) -> int:
    items = load()
    changes = sync_items(items)
    if changes:
        save(items)
    print("\n".join(changes) or "nothing to sync")
    return 0


def plan(items: list[dict], start: dt.date, days: int, hours: dict[str, float]) -> dict:
    window = [(start + dt.timedelta(days=i)).isoformat() for i in range(days)]
    left = {d: float(hours.get(d, 0)) for d in window}
    agenda = {d: [] for d in window}
    overflow, late = [], []
    for t in sorted([t for t in items if t["status"] in OPEN], key=sort_key):
        if t["status"] == "delegated":
            state = task_state(t.get("task", "")) or "unknown"
            need = float(t.get("review_h", 0.25)) if state in WAITING_ON_PM or state == "done" else 0.0
            if need == 0:
                continue                     # the agent is still working; nothing for you yet
            entry = {"id": t["id"], "title": f"Review {t['mode']} result for: {t['title']}", "hours": need,
                     "task": t["task"]}
        else:
            entry = {"id": t["id"], "title": t["title"], "hours": float(t.get("estimate_h") or 0.5)}
        if t.get("due") and t["due"] < window[0]:
            late.append(entry)
        candidates = [d for d in window if not t.get("due") or d <= t["due"]] or window[:1]
        slot = next((d for d in candidates if left[d] >= entry["hours"]), None)
        if slot:
            agenda[slot].append(entry)
            left[slot] -= entry["hours"]
        else:
            overflow.append({**entry, "due": t.get("due")})
    return {"days": agenda, "free_left": {d: round(v, 2) for d, v in left.items()},
            "overflow": overflow, "overdue": late}


def cmd_plan(a) -> int:
    start = dt.date.fromisoformat(a.start) if a.start else dt.date.today()
    hours = json.loads(a.hours) if a.hours else {}
    for i in range(a.days):
        d = start + dt.timedelta(days=i)
        if d.isoformat() not in hours:
            hours[d.isoformat()] = 0.0 if (d.weekday() >= 5 and not a.weekends) else a.default_hours
    result = plan(load(), start, a.days, hours)
    if a.json:
        print(json.dumps(result, indent=2))
        return 0
    for d, entries in result["days"].items():
        day = dt.date.fromisoformat(d).strftime("%a %b %d")
        print(f"{day}  ({hours[d]}h free, {result['free_left'][d]}h left)")
        for e in entries:
            print(f"  - {e['id']}  {e['title']}  [{e['hours']}h]")
    if result["overdue"]:
        print("Overdue: " + ", ".join(e["id"] for e in result["overdue"]))
    if result["overflow"]:
        print("Doesn't fit: " + ", ".join(f"{e['id']} ({e['hours']}h)" for e in result["overflow"]))
    return 0


def cmd_apply(a) -> int:
    ops = json.loads(Path(a.diff).read_text(encoding="utf-8"))
    if not isinstance(ops, list):
        raise TodoError("a diff is a JSON list of operations")
    items = load()
    work = json.loads(json.dumps(items))          # apply to a copy; save only if every op succeeds
    applied = []
    for op in ops:
        kind = op.get("op")
        if kind == "add":
            item = new_item(work, op.get("title", ""), op.get("due"), op.get("estimate_h"),
                            op.get("priority"), op.get("notes"))
            work.append(item)
            applied.append(f"added {item['id']}")
        elif kind in ("edit", "reschedule"):
            t = find(work, op["id"])
            for field in ("title", "notes"):
                if field in op:
                    t[field] = op[field]
            if "due" in op:
                t["due"] = check_date(op["due"])
            if "estimate_h" in op:
                t["estimate_h"] = float(op["estimate_h"])
            if "priority" in op:
                t["priority"] = int(op["priority"])
            applied.append(f"edited {op['id']}")
        elif kind in ("done", "drop"):
            t = find(work, op["id"])
            t["status"], t["closed"] = ("done" if kind == "done" else "dropped"), today()
            applied.append(f"{t['status']} {op['id']}")
        else:
            raise TodoError(f"unknown op '{kind}' (add, edit, reschedule, done, drop)")
    save(work)
    print(json.dumps({"applied": applied}, indent=2))
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    ad = sub.add_parser("add")
    ad.add_argument("title")
    ad.add_argument("--due")
    ad.add_argument("--estimate", type=float)
    ad.add_argument("--priority", type=int)
    ad.add_argument("--notes")
    ad.set_defaults(fn=cmd_add)
    ls = sub.add_parser("list")
    ls.add_argument("--all", action="store_true")
    ls.add_argument("--json", action="store_true")
    ls.set_defaults(fn=cmd_list)
    ed = sub.add_parser("edit")
    ed.add_argument("id")
    ed.add_argument("--title")
    ed.add_argument("--due")
    ed.add_argument("--estimate", type=float)
    ed.add_argument("--priority", type=int)
    ed.add_argument("--notes")
    ed.set_defaults(fn=cmd_edit)
    for name, status in (("done", "done"), ("drop", "dropped")):
        c = sub.add_parser(name)
        c.add_argument("id")
        c.add_argument("--note")
        c.set_defaults(fn=lambda a, s=status: close(a, s))
    lk = sub.add_parser("link")
    lk.add_argument("id")
    lk.add_argument("task")
    lk.add_argument("--mode", required=True)
    lk.add_argument("--instructions")
    lk.add_argument("--review-h", type=float, default=0.25, dest="review_h")
    lk.set_defaults(fn=cmd_link)
    sub.add_parser("sync").set_defaults(fn=cmd_sync)
    pl = sub.add_parser("plan")
    pl.add_argument("--days", type=int, default=5)
    pl.add_argument("--start")
    pl.add_argument("--hours", help='free hours per day as JSON, e.g. {"2026-10-26": 3.5}')
    pl.add_argument("--default-hours", type=float, default=6.0)
    pl.add_argument("--weekends", action="store_true", help="plan weekends at --default-hours")
    pl.add_argument("--json", action="store_true")
    pl.set_defaults(fn=cmd_plan)
    ap = sub.add_parser("apply")
    ap.add_argument("diff")
    ap.set_defaults(fn=cmd_apply)
    a = p.parse_args()
    try:
        return a.fn(a)
    except TodoError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

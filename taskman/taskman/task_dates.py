"""A board task's first-found, start and end dates, derived from the raw event log.

Stdlib-only: `bin/` imports this without the venv. Reads raw events, not
`replay()`, because replay folds history into current state and loses *when*
each field changed. Nothing here is stored — dates are derived on read.
"""

from __future__ import annotations

import json
from pathlib import Path


def read_events(board_dir: Path) -> list[dict]:
    """Every JSON object line of board_dir/events.jsonl; unparseable lines skipped."""
    events = []
    with open(Path(board_dir) / "events.jsonl", encoding="utf-8") as fh:
        for line in fh:
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if isinstance(event, dict):
                events.append(event)
    return events


def _plan_stem(tags) -> str | None:
    for tag in tags or ():
        if isinstance(tag, str) and tag.startswith("plan:"):
            return tag[len("plan:"):]
    return None


def all_task_dates(events: list[dict]) -> dict[int, dict]:
    """One pass over the log; task id -> the same dict `task_dates` returns."""
    acc: dict[int, dict] = {}
    for event in events:
        etype, tid, ts = event.get("type"), event.get("id"), event.get("ts")
        fields = event.get("fields") or {}
        if etype == "task.add":
            acc[tid] = {"found": ts or fields.get("created_at"), "tags": None,
                        "planned": None, "linked": None, "in_progress": None,
                        "done": None, "done_session": None}
        elif etype == "task.link":
            # rule 3: linked to a task that carries a plan: tag at link time
            task, target = acc.get(tid), acc.get(event.get("target"))
            stem = _plan_stem(target["tags"]) if target else None
            if task is not None and stem and task["linked"] is None:
                task["linked"] = (ts, stem)
            continue
        elif etype != "task.set":
            continue
        task = acc.get(tid)
        if task is None:
            continue
        # task.add and task.set share one fields shape; the add is simply first,
        # so a plan tag on the add is rule 1 and on a later set is rule 2.
        if "tags" in fields:
            task["tags"] = fields["tags"]
        stem = _plan_stem(fields.get("tags"))
        if stem and task["planned"] is None:
            task["planned"] = (ts, stem)
        status = fields.get("status")
        if status == "in_progress" and task["in_progress"] is None:
            task["in_progress"] = ts
        if status == "done":
            task["done"], task["done_session"] = ts, event.get("session")
        elif status is not None:  # moved off done (reopened) -> no end-date
            task["done"] = task["done_session"] = None
    return {tid: _resolve(task) for tid, task in acc.items()}


def _resolve(task: dict) -> dict:
    # Start-date rule order: planned (born / retagged, then linked) beats in_progress.
    planned = task["planned"] or task["linked"]
    if planned:
        started, stem = planned
        how = "planned"
    elif task["in_progress"]:
        started, how, stem = task["in_progress"], "in_progress", None
    else:
        started = how = stem = None
    return {"found": task["found"], "started": started, "started_how": how,
            "stem": stem, "done": task["done"], "done_session": task["done_session"]}


def task_dates(events: list[dict], task_id: int) -> dict | None:
    return all_task_dates(events).get(task_id)

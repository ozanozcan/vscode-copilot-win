"""The Board page's two models: `build()` turns the board into cards, `live()`
turns every running `docs/plans/*/dispatch/tracker.json` into a per-card overlay.

Both are pure and read-only (K1): the board replay, each plan's dispatch
INDEX and the trackers `/mow go` already writes. Membership and lane letters
are the roadmap's rules, reused from `roadmap` and `mow.preflight`, never
restated here.

A tracker todo maps to a card by its `#N` id only (K11). Any other id — a
slug, or a bare brief number such as `01` — maps through its lane's `brief`
to the task whose `source_ref` is that brief; a bare number is never a task
id. Only `running` trackers drive the overlay; every tracker, shipped
included, is read for where a review finding came from (K9).
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from taskman import roadmap
from taskman.eventlog import log, store
from taskman.mow.preflight import _split_lanes_table_extended

_PLANS = roadmap._PLANS
_TASK_ID = re.compile(r"#(\d{1,18})$")  # the one todo-id shape that is a task id (K11); bounded, so int() never
# meets a string past its 4300-digit limit (ValueError would escape the per-tracker guard and 500 the endpoint)
_BRIEF_PREFIX = re.compile(r"^\d{2}-[^:\s]+:\s+")  # `04-land-and-mirror: mirror …`
_TAG_PREFIXES = ("plan:", "kind:", "role:")
_FINDING = "review-finding"
STALE_AFTER_MINUTES = 4  # the mow tracker page's threshold (K12)
# What a tracker off the schema raises while it is walked: a string where a dict belongs, a number
# where a list belongs, a missing key. Caught per tracker, never per endpoint.
_SHAPE_ERRORS = (AttributeError, TypeError, KeyError)


def _brief_tasks(tasks: list[dict]) -> dict[str, dict]:
    """`docs/plans/<stem>/dispatch/<brief>` -> the lowest-id task with that source_ref."""
    by_ref: dict[str, dict] = {}
    for t in tasks:  # ids ascending, as in roadmap: a re-imported brief keeps its lowest id
        by_ref.setdefault(t.get("source_ref") or "", t)
    return by_ref


def _lanes(project_root: Path, by_ref: dict[str, dict]) -> dict[int, dict]:
    """task id -> {stem, letter, brief} for every lane in every plan's INDEX lanes table."""
    lanes: dict[int, dict] = {}
    for index in sorted((project_root / _PLANS).glob("*/dispatch/INDEX.md")):
        stem = index.parent.parent.name
        for row in _split_lanes_table_extended(index.read_text(encoding="utf-8")):
            task = by_ref.get(f"{_PLANS}{stem}/dispatch/{row['brief']}")
            if task is not None:
                lanes.setdefault(task["id"], {"stem": stem, "letter": row["lane"], "brief": row["brief"]})
    return lanes


def _done_at(board_dir: Path) -> dict[int, str]:
    """task id -> `ts` of the latest event that set it `done` (d#64).

    `store.state` has already replayed (and validated) this log; a second pass
    over the same lines keeps the timestamps the fold throws away. A reopen
    clears the entry, so a task done twice carries the later time.
    """
    done: dict[int, str] = {}
    try:
        raw = (board_dir / log.LOG_NAME).read_bytes()
    except FileNotFoundError:
        return done
    for line in raw.split(b"\n")[:-1]:  # the torn tail replay drops
        event = json.loads(line)
        if not event.get("type", "").startswith("task.") or "status" not in (event.get("fields") or {}):
            continue
        if event["fields"]["status"] == "done":
            done[event["id"]] = event.get("ts")
        else:
            done.pop(event["id"], None)
    return done


def _trackers(project_root: Path) -> list[dict]:
    """Every readable `docs/plans/*/dispatch/tracker.json`, stem order. A missing,
    unreadable or malformed file is skipped: one bad tracker must never take the
    endpoint down."""
    trackers = []
    for path in sorted((project_root / _PLANS).glob("*/dispatch/tracker.json")):
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, RecursionError):  # RecursionError: nested past the parser's limit
            continue
        if isinstance(doc, dict) and isinstance(doc.get("waves"), list):
            doc["stem"] = path.parent.parent.name  # the folder, whatever the file says: briefs map by it
            trackers.append(doc)
    return trackers


def _lane_rows(tracker: dict):
    """(wave number, lane dict) for every lane of `tracker`, tolerating gaps."""
    for wave in tracker["waves"]:
        if isinstance(wave, dict):
            for lane in wave.get("lanes") or []:
                if isinstance(lane, dict):
                    yield wave.get("wave"), lane


def _task_id(todo_id) -> int | None:
    """`#N` -> N. Anything else — a slug, a bare `01` — is not a task id (K11)."""
    m = _TASK_ID.fullmatch(str(todo_id).strip())
    return int(m.group(1)) if m else None


def _origins(trackers: list[dict]) -> dict[int, dict]:
    """task id -> {stem, wave, lane} from the first `findings[].task` naming it, any tracker (K9)."""
    origins: dict[int, dict] = {}
    for tracker in trackers:
        found: dict[int, dict] = {}
        try:
            for wave, lane in _lane_rows(tracker):
                for finding in lane.get("findings") or []:
                    task_id = _task_id((finding or {}).get("task"))
                    if task_id is not None:
                        found.setdefault(task_id, {"stem": tracker["stem"], "wave": wave, "lane": lane.get("lane")})
        except _SHAPE_ERRORS:
            continue  # this tracker is skipped whole; the others still name their findings
        for task_id, origin in found.items():
            origins.setdefault(task_id, origin)
    return origins


def _origin(task: dict, origins: dict[int, dict]) -> dict | None:
    if task["id"] in origins:
        return origins[task["id"]]
    for tag in task.get("tags") or []:
        if tag.startswith("plan:"):
            return {"stem": tag[len("plan:"):]}
    ref = task.get("source_ref") or ""
    return {"file": ref.rsplit("/", 1)[-1]} if ref else None


def _title(task: dict) -> str:
    return _BRIEF_PREFIX.sub("", task.get("title") or "", count=1)


def _card(task: dict, lane: dict | None, done_at: str | None, origins: dict[int, dict],
          live: bool) -> dict:
    tags = task.get("tags") or []
    card = {
        "id": task["id"],
        "title": _title(task),
        "status": task.get("status", ""),
        "priority": task.get("priority") or "med",
        "kind": next((t[len("kind:"):] for t in tags if t.startswith("kind:")), None),
        "labels": [t for t in tags if not t.startswith(_TAG_PREFIXES)],
        "plans": sorted(roadmap._stems(task)),
        "lane": lane,
        "agent": lane is not None or live,  # K3
        "blocked_by": sorted(task.get("blocked_by") or []),
        "claimed_by": task.get("claimed_by"),
        "done_at": done_at,
    }
    if _FINDING in tags:  # only finding cards carry the key (d#63)
        card["origin"] = _origin(task, origins)
    return card


def _running(trackers: list[dict]) -> list[dict]:
    return [t for t in trackers if t.get("run_status") == "running"]


def _map_todo(todo: dict, tracker: dict, lane: dict, by_ref: dict[str, dict]) -> int | None:
    """The card a tracker todo lands on: its `#N`, else its lane's brief task, else None (K11)."""
    task_id = _task_id(todo.get("id"))
    if task_id is not None:
        return task_id
    task = by_ref.get(f"{_PLANS}{tracker['stem']}/dispatch/{lane.get('brief')}")
    return task["id"] if task is not None else None


def _column(status: str | None, gate: str | None) -> str | None:
    """`## Live overlay rules`: where the todo's status plus its wave's gate put the card."""
    if status == "error" or gate == "error":
        return "blocked"
    if status == "running":
        return "in_progress"
    if status == "issues":
        return "review"
    if status == "done":
        return "done" if gate in ("done", "issues") else "review"  # #341: an `issues` gate flips the lanes it implicates
    return None  # pending, or a status this table does not know: the board's own column stands


def _agent_line(lane: dict) -> dict:
    """The lane's running agent, else its last; of it, the first running skill and tool."""
    agents = [a for a in lane.get("agents") or [] if isinstance(a, dict)]
    agent = next((a for a in agents if a.get("status") == "running"), agents[-1] if agents else None)
    if agent is None:
        return {"agent": None, "skill": None, "tool": None}
    first_running = lambda items: next(  # noqa: E731
        (i.get("name") for i in items or [] if isinstance(i, dict) and i.get("status") == "running"), None)
    return {"agent": agent.get("name"), "skill": first_running(agent.get("skills")),
            "tool": first_running(agent.get("tools"))}


def _findings(lane: dict) -> list[dict]:
    return [{"task": _task_id(f.get("task")), "severity": f.get("severity"), "title": f.get("title")}
            for f in lane.get("findings") or [] if isinstance(f, dict)]


def _stale_minutes(tracker: dict, now: datetime) -> int | None:
    """Whole minutes behind `now` when past the threshold, else None (K12)."""
    try:
        updated = datetime.fromisoformat(str(tracker.get("updated")).replace("Z", "+00:00"))
    except ValueError:
        return None
    if updated.tzinfo is None:
        updated = updated.replace(tzinfo=timezone.utc)
    minutes = int((now - updated).total_seconds() // 60)
    return minutes if minutes > STALE_AFTER_MINUTES else None


def _run(tracker: dict, by_ref: dict[str, dict], now: datetime) -> tuple[dict, dict]:
    """One running tracker's `runs[]` entry and the cards its todos land on."""
    unmapped, cards = [], {}
    for wave_n, lane in _lane_rows(tracker):
        gate = ((next((w for w in tracker["waves"] if isinstance(w, dict) and w.get("wave") == wave_n), {})
                 .get("gate") or {}).get("status"))
        for todo in lane.get("todos") or []:
            if not isinstance(todo, dict):
                continue
            task_id = _map_todo(todo, tracker, lane, by_ref)
            if task_id is None:
                unmapped.append(str(todo.get("id")))
                continue
            status = todo.get("status") or lane.get("status")
            cards.setdefault(str(task_id), {
                "column": _column(status, gate), "status": status, "gate": gate,
                "wave": wave_n, "lane": lane.get("lane"), "stem": tracker["stem"],
                **_agent_line(lane), "findings": _findings(lane)})
    run = {"stem": tracker["stem"], "title": tracker.get("title"),
           "updated": tracker.get("updated"), "stale_minutes": _stale_minutes(tracker, now),
           "unmapped": unmapped}
    return run, cards


def _overlay(trackers: list[dict], by_ref: dict[str, dict], now: datetime) -> dict:
    runs, cards = [], {}
    for tracker in _running(trackers):
        try:
            run, run_cards = _run(tracker, by_ref, now)
        except _SHAPE_ERRORS:
            continue  # this tracker is skipped whole; the other runs still render
        runs.append(run)
        for task_id, card in run_cards.items():
            cards.setdefault(task_id, card)
    return {"runs": runs, "cards": cards}


def build(project_root: Path) -> dict:
    """The board document for the project rooted at `project_root`."""
    board_dir = project_root / "board"
    state = store.state(board_dir)
    tasks = sorted(state["task"].values(), key=lambda t: t["id"])
    by_ref = _brief_tasks(tasks)
    lanes = _lanes(project_root, by_ref)
    done_at = _done_at(board_dir)
    trackers = _trackers(project_root)
    origins = _origins(trackers)
    live_ids = {int(i) for i in _overlay(trackers, by_ref, datetime.now(timezone.utc))["cards"]}
    plans = []
    for feature in sorted(state["feature"].values(), key=lambda f: f["id"]):
        if (stem := roadmap._feature_stem(feature)) is not None:
            plans.append({"stem": stem, "feature": feature["id"], "title": feature.get("title", "")})
    cards = [_card(t, lanes.get(t["id"]), done_at.get(t["id"]), origins, t["id"] in live_ids)
             for t in tasks if t.get("status") != "disabled"]
    return {
        "project": roadmap._project(project_root),
        "plans": plans,
        "disabled": sum(t.get("status") == "disabled" for t in tasks),
        "cards": cards,
    }


def live(project_root: Path, now: datetime | None = None) -> dict:
    """The live overlay: one run per `running` tracker, and the column each mapped card is in now.
    `now` is a parameter so the stale threshold can be pinned in tests."""
    tasks = sorted(store.state(project_root / "board")["task"].values(), key=lambda t: t["id"])
    return _overlay(_trackers(project_root), _brief_tasks(tasks), now or datetime.now(timezone.utc))

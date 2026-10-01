"""The project roadmap: milestones, prep, waves, lanes and edges.

Two sources only (docs-hub D4): the board replay and each plan's
`docs/plans/<stem>/dispatch/INDEX.md`. `build()` is pure — it returns the
JSON document `taskman roadmap --json` prints, and `to_markdown()` renders it.

Membership was learned from the real board: a task belongs to plan `<stem>`
by a `plan:<stem>` tag **or** a `source_ref` under `docs/plans/<stem>/` —
tag-only put 25 of 35 tasks in "no plan". A member is a lane when its
`source_ref` is that plan's `dispatch/<brief>` for a brief in the lanes table;
every other member is prep.

A task tagged for two plans is prep in both, so `total` is per-milestone, not
disjoint — don't sum totals for a project count. A task whose plans have no
milestone is listed in `loose`, so every board task is shown somewhere.
`after_plan` may name a stem with no feature; then no edge is drawn.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

from taskman.eventlog import store
from taskman.mow.preflight import (
    _CITATION,
    _WAVE_BULLET_RE,
    _split_lanes_table_extended,
    parse_wave_bullets,
)

_PLANS = "docs/plans/"
# `waived: d#N (why)` names a decision the lane deliberately does not follow.
_WAIVED = re.compile(r"waived:\s*d\s*`?#\d+`?(?:\s*\([^()]*\))?", re.I)
_WAVE_NOTE = re.compile(r"\s*\(([^)]*)\)")
_AFTER_PLAN = re.compile(r"after `([^`]+)` ships")


def _stems(task: dict) -> set[str]:
    stems = {t[len("plan:"):] for t in task.get("tags") or [] if t.startswith("plan:")}
    ref = task.get("source_ref") or ""
    if ref.startswith(_PLANS):
        stem, sep, _rest = ref[len(_PLANS):].partition("/")
        if sep and stem:  # docs/plans/<file>.md names no stem
            stems.add(stem)
    return stems


def _task_json(task: dict) -> dict:
    return {
        "id": task["id"],
        "title": task.get("title", ""),
        "status": task.get("status", ""),
        "priority": task.get("priority") or None,
        "blocked_by": sorted(task.get("blocked_by") or []),
    }


def _feature_stem(feature: dict) -> str | None:
    return next((t[len("plan:"):] for t in feature.get("tags") or [] if t.startswith("plan:")), None)


def _decisions(cell: str, titles: dict[int, str]) -> list[dict]:
    """Cited `d #N` pointers as {id, title}; an id not on the board -> null title (d#45)."""
    ids: list[int] = []
    for kind, num in _CITATION.findall(_WAIVED.sub(" ", cell)):
        if kind.lower() == "d" and int(num) not in ids:
            ids.append(int(num))
    return [{"id": n, "title": titles.get(n)} for n in ids]


def _wave_notes(index_text: str) -> dict[str, str]:
    """wave -> the parenthetical note on its ## Waves bullet (the parsers drop it)."""
    notes: dict[str, str] = {}
    in_waves = False
    for line in index_text.splitlines():
        if line.startswith("## Waves"):
            in_waves = True
            continue
        if in_waves and line.startswith("## "):
            break
        m = _WAVE_BULLET_RE.match(line.strip()) if in_waves else None
        if m:  # a repeated bullet: last wins, as in parse_wave_bullets
            note = _WAVE_NOTE.match(line.strip(), m.end())
            notes[m.group(1)] = note.group(1).strip() if note else ""
    return notes


def _waves(index_text: str, lanes_by_letter: dict[str, dict], lane_tasks: dict[str, dict],
           titles: dict[int, str]) -> list[dict]:
    letters_by_wave, _unparsed = parse_wave_bullets(index_text)
    notes = _wave_notes(index_text)
    waves = []
    for n, letters in letters_by_wave.items():
        lanes = []
        for letter in letters:
            task = lane_tasks.get(letter)
            if task is None:
                continue
            row = lanes_by_letter[letter]
            lanes.append({"letter": letter, "brief": row["brief"], **_task_json(task),
                          "decisions": _decisions(row["decisions"], titles)})
        note = notes.get(n, "")
        after = _AFTER_PLAN.search(note)
        waves.append({"n": n, "note": note, "after_plan": after.group(1) if after else None,
                      "lanes": lanes})
    return waves


def _project(project_root: Path) -> dict:
    """Identity from `project_root`'s own marker, read the way config.find_project reads it."""
    marker = project_root / ".taskman.toml"
    data = tomllib.loads(marker.read_text(encoding="utf-8"))
    proj = data.get("project", data)
    if not proj.get("slug"):
        raise ValueError(f"{marker} has no project.slug")
    return {"slug": proj["slug"], "name": proj.get("name", proj["slug"])}


def build(project_root: Path) -> dict:
    """The roadmap document for the project rooted at `project_root`."""
    state = store.state(project_root / "board")
    tasks = sorted(state["task"].values(), key=lambda t: t["id"])
    titles = {i: d.get("title") for i, d in state["decision"].items()}
    ordered = sorted(state["feature"].values(), key=lambda f: f["id"])
    feature_of: dict[str, int] = {}
    for feature in ordered:
        if (stem := _feature_stem(feature)) is not None:
            feature_of.setdefault(stem, feature["id"])
    features = []
    edges = [{"from": t["id"], "to": b, "kind": "blocked_by"}
             for t in tasks for b in sorted(t.get("blocked_by") or [])]
    for feature in ordered:
        stem = _feature_stem(feature)
        members = [t for t in tasks if stem is not None and stem in _stems(t)]
        index = project_root / _PLANS / str(stem) / "dispatch" / "INDEX.md"
        index_text = index.read_text(encoding="utf-8") if stem and index.is_file() else ""
        lanes_by_letter = {row["lane"]: row for row in _split_lanes_table_extended(index_text)}
        by_ref: dict[str, dict] = {}
        for t in members:  # ids ascending: a re-imported brief keeps its lowest id as the lane
            by_ref.setdefault(t.get("source_ref"), t)
        lane_tasks = {
            letter: by_ref[ref]
            for letter, row in lanes_by_letter.items()
            if (ref := f"{_PLANS}{stem}/dispatch/{row['brief']}") in by_ref
        }
        waves = _waves(index_text, lanes_by_letter, lane_tasks, titles)
        placed = {lane["id"] for wave in waves for lane in wave["lanes"]}
        edges += [{"from": lane["id"], "to": feature_of[w["after_plan"]], "kind": "after_plan"}
                  for w in waves if w["after_plan"] in feature_of for lane in w["lanes"]]
        features.append({
            "id": feature["id"],
            "title": feature.get("title", ""),
            "stem": stem,
            "track": "platform" if feature.get("lane") == "platform" else "product",
            "status": feature.get("status", ""),
            "done": sum(t.get("status") == "done" for t in members),
            "total": len(members),
            "prep": [_task_json(t) for t in members if t["id"] not in placed],
            "waves": waves,
        })
    loose = [_task_json(t) for t in tasks if not (_stems(t) & feature_of.keys())]
    return {"project": _project(project_root), "features": features, "loose": loose,
            "edges": edges}


def _task_line(task: dict, prefix: str = "") -> str:
    parts = [f"- {prefix}#{task['id']} {task['title']}  [{task['status']}]"]
    if task["priority"]:
        parts.append(f"({task['priority']})")
    if task.get("brief"):
        parts.append(f"· {task['brief']}")
    for d in task.get("decisions", ()):
        parts.append(f"· d#{d['id']}" + (f" {d['title']}" if d["title"] else ""))
    if task["blocked_by"]:
        parts.append("· blocked by " + ", ".join(f"#{b}" for b in task["blocked_by"]))
    return " ".join(parts)


def to_markdown(doc: dict) -> str:
    """The roadmap document as markdown, milestones in id order."""
    lines = [f"# Roadmap — {doc['project']['name']}", ""]
    if not doc["features"]:
        lines += ["No milestones yet — `/mow plan` creates them.", ""]
    for f in doc["features"]:
        stem = f" · {f['stem']}" if f["stem"] else ""
        lines += [f"## #{f['id']} {f['title']}  [{f['status']}] · {f['track']}{stem}"
                  f" · {f['done']}/{f['total']} done", ""]
        if f["prep"]:
            lines += ["Prep:"] + [_task_line(t) for t in f["prep"]] + [""]
        for w in f["waves"]:
            note = f" ({w['note']})" if w["note"] else ""
            lines += [f"### Wave {w['n']}{note}"]
            lines += [_task_line(lane, f"{lane['letter']}  ") for lane in w["lanes"]] + [""]
    if doc["loose"]:
        lines += ["## Not on the roadmap", ""] + [_task_line(t) for t in doc["loose"]] + [""]
    return "\n".join(lines)

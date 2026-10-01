"""Report what nothing on the board consumes, and which checkpoints are spent.

Three quarters of one project's decisions had no recorded consumer, and
nothing on the board knew a checkpoint existed (d#81, d#83). This is the read
side of the `cited_by` relation and the `checkpoint:<slug>` tag:

  - **unconsumed** — decisions and captures with no `cited_by` and no
    `task_id`; requirements with no `cited_by` (an owner is not a consumer;
    `removed` requirements are skipped). Oldest first, with age in days and
    `by` = the add event's `session` stamp, or `-` (d#84: never a time window).
  - **conventions** — decisions with no `plan:` tag and at least one `path:` /
    `area:` tag. Tag surfacing consumes them, so they are a count, never
    listed (d#86).
  - **stale checkpoints** — `open` / `in-progress` rows in
    `docs/checkpoints/INDEX.md` whose tasks (the file's `## Board tasks` ids
    plus every task tagged `checkpoint:<slug>`) are all `done` or `disabled`.

It informs and never blocks: exit is always 0 (d#84). It only reads.

Usage:
  python -m taskman.mow.audit_links --board board --checkpoints docs/checkpoints
      [--min-age-days 7] [--kind grill,plan] [--json]
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

CLOSED = frozenset({"done", "disabled"})
LIVE_CHECKPOINT = frozenset({"open", "in-progress", "in_progress"})
ENTITIES = ("decision", "capture", "requirement")
POINTER = "run wrapup-audit-links for the full list"


@dataclass
class Item:
    entity: str
    id: int
    title: str
    age_days: int
    by: str
    created: str = field(default="", repr=False)


@dataclass
class Stale:
    slug: str
    task_ids: list[int]


@dataclass
class AuditReport:
    unconsumed: list[Item]
    conventions: int
    stale_checkpoints: list[Stale]

    def count(self, entity: str) -> int:
        return sum(1 for i in self.unconsumed if i.entity == entity)


def is_convention(tags) -> bool:
    """d#86: no `plan:<stem>` tag and at least one `path:` or `area:` tag."""
    tags = [str(t) for t in tags or ()]
    if any(t.startswith("plan:") for t in tags):
        return False
    return any(t.startswith(("path:", "area:")) for t in tags)


def _when(raw) -> datetime | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        when = datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return when if when.tzinfo else when.replace(tzinfo=timezone.utc)


def _add_events(board_dir: Path) -> dict[tuple[str, int], dict]:
    """(entity, id) -> its add event. Replay drops `session`; the log keeps it."""
    from taskman.task_dates import read_events

    return {
        (e["type"].split(".", 1)[0], e.get("id")): e
        for e in read_events(board_dir)
        if isinstance(e.get("type"), str) and e["type"].split(".", 1)[0] in ENTITIES
        and e["type"].endswith(".add")
    }


def _consumed(entity: str, row: dict) -> bool:
    if row.get("cited_by") or []:
        return True
    return entity != "requirement" and row.get("task_id") is not None


def _unconsumed(state, adds, *, min_age_days, capture_kinds, now) -> tuple[list[Item], int]:
    items: list[Item] = []
    conventions = 0
    for entity in ENTITIES:
        for eid, row in state.get(entity, {}).items():
            if entity == "requirement" and row.get("status") == "removed":
                continue
            if entity == "capture" and row.get("kind") not in capture_kinds:
                continue
            if entity == "decision" and is_convention(row.get("tags")):
                conventions += 1
                continue
            if _consumed(entity, row):
                continue
            add = adds.get((entity, eid), {})
            created = _when(row.get("created_at")) or _when(add.get("ts"))
            age = max(0, (now - created).days) if created else 0  # clock skew: never negative
            if age < min_age_days:
                continue
            title = row.get("title") or row.get("summary") or ""
            session = add.get("session")
            items.append(Item(
                entity=entity, id=eid, title=str(title).splitlines()[0] if title else "",
                age_days=age, by=str(session)[:8] if session else "-",
                created=created.isoformat() if created else "",
            ))
    items.sort(key=lambda i: (-i.age_days, i.created, ENTITIES.index(i.entity), i.id))
    return items, conventions


_ROW_IDS = re.compile(r"^\s*[-*]\s+((?:[~*`\s]*#\d+[~*`]*\s*(?:[/,&]\s*)?)+)")


def _listed_ids(text: str) -> list[int]:
    """Ids that open a bullet under `## Board tasks` — not ids named later in it
    (`· blocked by #3` is a blocker, not one of this checkpoint's tasks)."""
    m = re.search(r"(?m)^## Board tasks\s*$", text)
    if not m:
        return []
    section = text[m.end():]
    stop = re.search(r"(?m)^## ", section)
    if stop:
        section = section[: stop.start()]
    ids: list[int] = []
    for line in section.splitlines():
        lead = _ROW_IDS.match(line)
        if lead:
            ids.extend(int(x) for x in re.findall(r"#(\d+)", lead.group(1)))
    return ids


def _index_rows(index: Path) -> list[tuple[str, str]]:
    """(slug, status) per INDEX.md table row, columns found by header name."""
    cols: list[str] | None = None
    rows = []
    for line in index.read_text(encoding="utf-8").splitlines():
        if not line.lstrip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if cols is None:
            cols = [c.lower() for c in cells]
            continue
        if set("".join(cells)) <= set("-: "):
            continue
        if "slug" in cols and "status" in cols and len(cells) == len(cols):
            rows.append((cells[cols.index("slug")], cells[cols.index("status")].lower()))
    return rows


def _stale(state, checkpoints_dir: Path | None) -> list[Stale]:
    if checkpoints_dir is None or not (checkpoints_dir / "INDEX.md").is_file():
        return []
    tasks = state.get("task", {})
    out: list[Stale] = []
    for slug, status in _index_rows(checkpoints_dir / "INDEX.md"):
        if status not in LIVE_CHECKPOINT:
            continue
        path = checkpoints_dir / f"{slug}.md"
        ids = set(_listed_ids(path.read_text(encoding="utf-8"))) if path.is_file() else set()
        tag = f"checkpoint:{slug}"
        ids |= {tid for tid, t in tasks.items() if tag in (t.get("tags") or [])}
        if not ids:
            continue
        # An id the board does not know is not provably closed.
        if all(tasks.get(tid, {}).get("status") in CLOSED for tid in ids):
            out.append(Stale(slug=slug, task_ids=sorted(ids)))
    return out


def audit(
    board_dir: Path,
    checkpoints_dir: Path | None,
    *,
    min_age_days: int = 7,
    capture_kinds: tuple[str, ...] = ("grill", "plan"),
    now: datetime | None = None,
) -> AuditReport:
    from taskman.eventlog import store

    state = store.state(board_dir)
    items, conventions = _unconsumed(
        state, _add_events(board_dir), min_age_days=min_age_days,
        capture_kinds=tuple(capture_kinds), now=now or datetime.now(timezone.utc),
    )
    return AuditReport(items, conventions, _stale(state, checkpoints_dir))


def _item_line(i: Item) -> str:
    return f"- {i.entity} #{i.id}  {i.age_days}d  by {i.by}  {i.title}"


def format_report(report: AuditReport, *, limit: int | None = None) -> str:
    """limit=None: every item, oldest first. limit=N: counts, the N newest
    (newest first), every stale checkpoint, then the pointer (d#108)."""
    lines = [f"unconsumed {e}s: {report.count(e)}" for e in ENTITIES]
    lines.append(f"conventions: {report.conventions}")
    items = report.unconsumed if limit is None else report.unconsumed[::-1][:limit]
    if items:
        lines.append("")
        lines.append("unconsumed (oldest first):" if limit is None
                     else f"newest {len(items)} of {len(report.unconsumed)} unconsumed:")
        lines.extend(_item_line(i) for i in items)
    lines.append("")
    lines.append(f"stale checkpoints: {len(report.stale_checkpoints)}")
    for s in report.stale_checkpoints:
        ids = " ".join(f"#{t}" for t in s.task_ids)
        lines.append(f"- {s.slug}  (all done/disabled: {ids})")
    if limit is not None:
        lines.append("")
        lines.append(POINTER)
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="wrapup-audit-links", description=__doc__.split("\n")[0])
    ap.add_argument("--board", default="board", help="board dir (default: ./board)")
    ap.add_argument("--checkpoints", default=None, help="docs/checkpoints dir (optional)")
    ap.add_argument("--min-age-days", type=int, default=7)
    ap.add_argument("--kind", default="grill,plan", help="capture kinds (default grill,plan)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    kinds = tuple(k.strip() for k in args.kind.split(",") if k.strip())
    try:
        report = audit(
            Path(args.board), Path(args.checkpoints) if args.checkpoints else None,
            min_age_days=args.min_age_days, capture_kinds=kinds,
        )
    except (OSError, ValueError) as exc:
        # Informs, never blocks (d#84): say why, exit 0.
        print(f"audit not run: {exc}")
        return 0
    if args.json:
        doc = asdict(report)
        for item in doc["unconsumed"]:
            item.pop("created", None)
        print(json.dumps(doc, indent=2))
    else:
        print(format_report(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

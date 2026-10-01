#!/usr/bin/env python3
"""Reconcile a mow stem's tracker.json against what a finished run must look like.

/mow go §4 spends a whole subagent on this: spawn a `general-purpose` reader to
diff the board against reality and "report only discrepancies — lanes/agents left
`running` that actually finished, findings without taskman ids, any agent missing
`started`/`ended`, wave `started`/`ended` gaps". Most of that list is a query over
structured JSON, and a subagent's one-off probe leaves no artifact you can point
at later (L42). This is the mechanical half; the subagent keeps the semantic half
it is actually needed for — artifacts that were invented, lanes whose board status
disagrees with their own `## Verification` block.

Errors vs warnings follow the schema (skills/mow/TRACKER.md), not preference.
`started`/`ended` are documented **optional** with "omit rather than guess", so a
gap is reported and never blocks — gating on it would be stricter than the format
allows. A non-terminal status at close-out, a finding with no board row — checked by
resolving the id against the board, not merely by the field being filled — or a
`run_status` still `running` are unambiguous, and those refuse. So does a lane test
count the lane's verification record does not contain (L104), for runs started on
or after GATES_FROM.

A stem with no tracker.json never ran one; this no-ops.

Usage:
  python -m taskman.mow.check_tracker docs/plans/<stem>

Exit 0 = board matches (warnings may print). Exit 1 = refuse the `shipped` flip.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

TERMINAL = frozenset({"done", "issues", "error"})
CLOSED = frozenset({"done", "disabled"})  # board statuses that mean a finding no longer stands
VOCABULARY = TERMINAL | {"pending", "running"}


def _tracker_path(stem_dir: Path) -> Path:
    stem = stem_dir.parent if stem_dir.name == "dispatch" else stem_dir
    return stem / "dispatch" / "tracker.json"


def _status_error(label: str, status: object) -> str | None:
    if not isinstance(status, str) or status not in VOCABULARY:
        return f"{label}: status {status!r} is outside the schema vocabulary"
    if status not in TERMINAL:
        return f"{label}: still `{status}` at close-out — a finished run has no pending work"
    return None


# (lane label, finding title, task id, lane status, wave label, gate status)
Cited = tuple[str, str, str, object, str, object]


def _walk(data: dict) -> tuple[list[str], list[str], list[Cited]]:
    errors: list[str] = []
    cited: list[Cited] = []
    warnings: list[str] = []

    for wave in data.get("waves") or []:
        wn = f"wave {wave.get('wave', '?')}"
        if err := _status_error(wn, wave.get("status")):
            errors.append(err)

        gate = wave.get("gate")
        gate_status = gate.get("status") if isinstance(gate, dict) else None
        if not isinstance(gate, dict):
            errors.append(f"{wn}: no `gate` — every wave ends with a review gate (§2b)")
        elif err := _status_error(f"{wn} gate", gate.get("status")):
            errors.append(err)

        for field in ("started", "ended"):
            if not wave.get(field):
                warnings.append(f"{wn}: no `{field}` — the wave duration on the board comes from nothing else")

        for lane in wave.get("lanes") or []:
            ln = f"{wn} lane {lane.get('lane', '?')}"
            if err := _status_error(ln, lane.get("status")):
                errors.append(err)

            findings = lane.get("findings") or []
            if lane.get("status") == "issues" and not findings:
                errors.append(
                    f"{ln}: status `issues` with no `findings[]` — a lane goes issues "
                    "only once its findings are filed on the board"
                )
            for f in findings:
                task_id = str(f.get("task") or "").strip()
                if not task_id:
                    errors.append(
                        f"{ln}: finding {f.get('title', '?')!r} has no `task` id — "
                        "no board row, not a tracked finding"
                    )
                else:
                    cited.append((ln, f.get("title", "?"), task_id, lane.get("status"), wn, gate_status))

            for todo in lane.get("todos") or []:
                if err := _status_error(f"{ln} todo {todo.get('id', '?')}", todo.get("status")):
                    errors.append(err)

            for agent in lane.get("agents") or []:
                an = f"{ln} agent {agent.get('name', '?')}"
                if err := _status_error(an, agent.get("status")):
                    errors.append(err)
                for field in ("started", "ended"):
                    if not agent.get(field):
                        warnings.append(
                            f"{an}: no `{field}` — the per-subagent duration beside its "
                            "name comes from nothing else"
                        )
                pending = [
                    s.get("name", "?") for s in (agent.get("skills") or [])
                    if s.get("status") == "pending"
                ]
                if pending:
                    warnings.append(
                        f"{an}: skills never reconciled against the lane's Verification "
                        f"block: {', '.join(pending)}"
                    )

    return errors, warnings, cited


def _unresolved_findings(stem_dir: Path, cited: list[Cited]) -> list[str]:
    """Every finding id must name a row that exists.

    The field being non-empty only proves someone typed something. An id typed
    from context — continuing a numbering sequence you saw earlier in the
    session — reads exactly like a filed one and passes every downstream check,
    while a reader who follows it finds nothing, or worse finds an unrelated
    row. So resolve it against the board that issues ids (L69).

    **This catches only the dangling half, and the other half is the dangerous
    one.** A typed id that happens to land on an existing row passes here and is
    invisible everywhere downstream. That is not hypothetical: the run that
    prompted this guard typed `#12233` for a latent tracker finding, and `#12233`
    was a live high-priority row from another stem's planning — a production
    Tailwind build bug. The gate would have said OK. So this is a backstop for
    the obvious case, never a licence to type an id: file the row and use what
    the tool returns.

    No board in this repo means nothing to resolve against; that is not a
    finding's fault, so it no-ops rather than refusing.

    The same lookup settles the status rule (TRACKER.md write-points: findings
    filed -> gate + affected lanes `issues`). A finding whose row is still open
    means the lane and its wave's gate cannot be `done`. A closed row was fixed
    in the run, and `done` is then honest. A fresh reconcile reader was the only
    thing that caught this at commit-own's close-out (#76); mow-start-lights
    shipped with it unnoticed.
    """
    if not cited:
        return []
    stem = stem_dir.parent if stem_dir.name == "dispatch" else stem_dir
    if stem.parent.name == "plans" and stem.parent.parent.name == "docs":
        repo_root = stem.parent.parent.parent
    else:
        repo_root = stem.parent.parent.parent
    board_dir = repo_root / "board"
    if not (repo_root / ".taskman.toml").is_file() or not board_dir.is_dir():
        return []
    try:
        from taskman.eventlog import store
        tasks = store.state(board_dir).get("task", {})
    except Exception:
        return []

    errors: list[str] = []
    done_over_open: dict[str, list[str]] = {}
    for label, title, task_id, lane_status, wave_label, gate_status in cited:
        raw = task_id.lstrip("#").strip()
        if not raw.isdigit() or int(raw) not in tasks:
            errors.append(
                f"{label}: finding {title!r} cites {task_id} — no such row on the "
                "board. An id typed from context is a claim that a record exists; "
                "file the row and use the id the tool returns (L69)"
            )
            continue
        if tasks[int(raw)].get("status") in CLOSED:
            continue
        for who, status in ((label, lane_status), (f"{wave_label} gate", gate_status)):
            if status == "done":
                done_over_open.setdefault(who, []).append(f"#{raw}")
    for who, ids in done_over_open.items():
        errors.append(
            f"{who}: `done` while its finding(s) {', '.join(ids)} are still open on the "
            "board — findings filed means the gate and the affected lanes go `issues`"
        )
    return errors

# Refusals added after runs were already live apply only to runs that started on or
# after the day they landed — a run must not be failed at close-out by a gate that
# did not exist when it started. Same precedent as check_action_report's
# RUN_REPORT_CUTOFF. Set to the day *after* the landing day: unit-view,
# taskman-single-source-of-truth and lessons-to-guards all started on 2026-09-30,
# before the lane landed that day, and a day-granular cutoff cannot tell them apart
# from a run started after it. A run with no `started` is treated as older.
GATES_FROM = "2026-10-01"


def gated(data: dict) -> bool:
    """Does the post-landing close-out gate set (L103, L104) apply to this run?"""
    started = data.get("started")
    return isinstance(started, str) and started[:10] >= GATES_FROM


# A test count as the tracker writes it: `pytest -q (41 passed)` or `tests: 41`.
# debt: two shapes only — `(16 checks)`, `8/8 pass` and mutant counts go unchecked;
# add a shape when one of them recurs hand-typed.
_COUNT = re.compile(r"\b(\d+) passed\b|\btests?\s*[:=]\s*(\d+)\b", re.I)
_TEXT = frozenset({".md", ".txt"})  # records are prose; screenshots beside them are not


def _run_output(lane: dict):
    """The lane fields that carry run output — findings, todos and the brief name are prose."""
    yield lane.get("detail")
    for agent in lane.get("agents") or []:
        yield agent.get("detail")
        for tool in agent.get("tools") or []:
            yield tool.get("name")
            yield tool.get("detail")


def _in_record(n: str, unit: str, text: str) -> bool:
    """Does `text` print count `n` with the unit the tracker gave it?"""
    if unit == "passed":
        return re.search(rf"(?<!\d){n} passed\b", text, re.I) is not None
    return re.search(rf"\btests?\s*[:=]\s*{n}(?!\d)", text, re.I) is not None


def _typed_counts(stem_dir: Path, data: dict) -> list[str]:
    """A lane's test count must appear as run output in the lane's own records (L104).

    A count written into the run record was typed rather than copied from the run
    that produced it; it reads exactly like a real one. The lane's
    `dispatch/verification/<brief>` is the copy of its own report and the expected
    home. A fix round changes the count and only its own record holds the new one,
    so every text file in `dispatch/verification/` whose name starts with the
    brief's stem counts too (`01-a.fix1.md`, `01-a-fix1.md`). Another lane's record
    vouches only for that lane. The count must carry the unit the tracker gave it —
    `41 passed` or `tests: 41` — so a date, a sha or a bare `41` does not match,
    and `41` inside `141` is not it. A lane with no count has nothing to check.
    """
    dispatch = _tracker_path(stem_dir).parent
    verification = dispatch / "verification"
    errors: list[str] = []
    for wave in data.get("waves") or []:
        for lane in wave.get("lanes") or []:
            counts: list[tuple[str, str]] = []
            for text in _run_output(lane):
                if not isinstance(text, str):
                    continue
                for m in _COUNT.finditer(text):
                    c = (m.group(1), "passed") if m.group(1) else (m.group(2), "tests")
                    if c not in counts:
                        counts.append(c)
            if not counts:
                continue
            ln = f"wave {wave.get('wave', '?')} lane {lane.get('lane', '?')}"
            brief = str(lane.get("brief") or "?")
            record_path = verification / brief
            prefix = Path(brief).stem
            paths = sorted(
                p for p in verification.iterdir()
                if p.is_file() and p.suffix in _TEXT and p.name.startswith(prefix)
            ) if verification.is_dir() else []
            texts = [p.read_text(encoding="utf-8", errors="replace") for p in paths]
            for n, unit in counts:
                if not any(_in_record(n, unit, t) for t in texts):
                    searched = ", ".join(p.name for p in paths) or "none"
                    shown = f"{n} passed" if unit == "passed" else f"tests: {n}"
                    errors.append(
                        f"{ln}: test count {n} in tracker.json does not appear as "
                        f"`{shown}` in {record_path} (the lane's record) or its "
                        f"fix-round records (searched: {searched}) — copy a count "
                        "from the output line of the run that produced it, never "
                        "type it (L104)"
                    )
    return errors


def _load(stem_dir: Path) -> tuple[dict | None, list[str]]:
    path = _tracker_path(stem_dir)
    if not path.is_file():
        return None, []
    try:
        return json.loads(path.read_text(encoding="utf-8")), []
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        return None, [f"{path}: unreadable ({exc})"]


def check_stem(stem_dir: Path) -> list[str]:
    data, errors = _load(stem_dir)
    if data is None:
        return errors

    path = _tracker_path(stem_dir)
    run_status = data.get("run_status")
    if run_status != "shipped":
        errors.append(
            f"{path}: run_status is {run_status!r}, not `shipped` — that flag is what "
            "moves this run from ?runs=live to ?runs=archive and what the "
            "still-running count reads; a run left `running` holds the board up for good"
        )

    walk_errors, _, cited = _walk(data)
    errors += walk_errors + _unresolved_findings(stem_dir, cited)
    if gated(data):
        errors += _typed_counts(stem_dir, data)
    return errors


def collect_warnings(stem_dir: Path) -> list[str]:
    """Discrepancies worth reporting that the schema permits — never blocking."""
    data, _ = _load(stem_dir)
    if data is None:
        return []
    _, warnings, _ = _walk(data)
    return warnings


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    stem = Path(args[0]).resolve()
    if not stem.exists():
        print(f"not found: {stem}", file=sys.stderr)
        return 2

    errors = check_stem(stem)
    for w in collect_warnings(stem):
        print(f"  ! {w}", file=sys.stderr)
    if errors:
        print("mow tracker reconcile FAILED:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1
    print(f"mow tracker reconcile OK: {stem}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

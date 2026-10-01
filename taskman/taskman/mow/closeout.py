#!/usr/bin/env python3
"""Deterministic mow close-out gate before a stem is flipped `shipped`.

The bookend to preflight. Preflight refuses fan-out until the run is fit to start;
this refuses `shipped` until the run has stopped lying about itself — a ship-check
verdict bound to the plan it reviewed, an action report that is actually written
and linked, and a tracker whose board matches a finished run.

Composes:
  - check_action_report — the report exists, has its sections, is linked from INDEX
  - check_ship_check    — the plan-vs-code verdict, its plan digest, its waivers
  - check_tracker       — no pending work, findings have board rows, run_status shipped
  - check_verification  — each INDEX lane wrote dispatch/verification/<brief>
  - check_board_sync    — when a board exists, dispatch tasks are actually `done`
  - a diary entry naming the stem, when the repo keeps docs/diary/ (L103)
  - a cross-artifact check neither of them can make alone: findings on the tracker
    must have a finding-triage record in the report (§4.1)

Deliberately a close-out gate, never a fan-out one: a missing doc section must
never refuse a legitimate `/mow go` (SKILL.md plan §6), but it should absolutely
refuse to let a half-recorded run call itself finished.

Usage:
  python -m taskman.mow.closeout docs/plans/<stem>
  python -m taskman.mow.closeout docs/plans/<stem> --json

Exit 0 = clear to ship. Exit 1 = refuse. Exit 2 = usage / stem not found.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from taskman.mow import (
    check_action_report,
    check_board_sync,
    check_ship_check,
    check_tracker,
    check_verification,
)


def _tracker_findings(stem_dir: Path) -> int:
    data, _ = check_tracker._load(stem_dir)
    if not data:
        return 0
    return sum(
        len(lane.get("findings") or [])
        for wave in (data.get("waves") or [])
        for lane in (wave.get("lanes") or [])
    )


def _missing_diary(stem_dir: Path) -> list[str]:
    """A repo that keeps `docs/diary/` must have an entry naming the run (L103).

    The diary step existed only as SKILL.md prose, and a run closed out without
    it. A link to `docs/plans/<stem>/` names the stem too, so one bounded match
    covers both — `demo` inside `demo-extra` is not a mention. No diary folder
    means the repo keeps none, and the check is silent. Applies only to runs
    started on or after check_tracker.GATES_FROM.
    """
    stem = stem_dir.parent if stem_dir.name == "dispatch" else stem_dir
    diary = stem.parent.parent / "diary"
    if not diary.is_dir():
        return []
    data, _ = check_tracker._load(stem_dir)
    if not data or not check_tracker.gated(data):
        return []
    # debt: rescans every diary file each close-out; index by date if it passes ~1k files.
    mention = re.compile(rf"(?<![\w-]){re.escape(stem.name)}(?![\w-])")
    for path in diary.rglob("*"):
        if path.is_file() and mention.search(path.read_text(encoding="utf-8", errors="replace")):
            return []
    return [
        f"no diary entry names `{stem.name}` — this repo keeps {diary}; write the run's "
        f"entry (its name or a link to docs/plans/{stem.name}/) before the shipped flip (L103)"
    ]


def run_closeout(stem_dir: Path) -> tuple[list[str], list[str]]:
    """Return (errors, warnings)."""
    errors = check_action_report.check_stem(stem_dir)

    # The ship-check verdict lives inside the action report; if the report is
    # missing, check_action_report already said so once — don't say it twice.
    report_missing = any("missing" in e and "action-report.md" in e for e in errors)
    if not report_missing:
        errors += check_ship_check.check_stem(stem_dir)

    errors += check_tracker.check_stem(stem_dir)
    errors += check_verification.check_stem(stem_dir)
    errors += check_board_sync.check_stem(stem_dir)
    errors += _missing_diary(stem_dir)

    findings = _tracker_findings(stem_dir)
    if findings and not check_action_report.has_triage_record(stem_dir):
        errors.append(
            f"{findings} finding(s) on the tracker but no finding-triage record in the "
            "action report — §4.1 classifies every Critical/Major finding "
            "(a) mechanizable / (b) convention / (c) one-off before the report is written"
        )

    return errors, check_tracker.collect_warnings(stem_dir)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("stem", type=Path, help="docs/plans/<stem> or …/<stem>/dispatch")
    p.add_argument("--json", action="store_true", help="machine-readable result on stdout")
    args = p.parse_args(sys.argv[1:] if argv is None else argv)

    stem = args.stem.resolve()
    if not stem.exists():
        msg = f"not found: {stem}"
        if args.json:
            print(json.dumps({"ok": False, "stem": str(stem), "errors": [msg]}))
        else:
            print(msg, file=sys.stderr)
        return 2

    errors, warnings = run_closeout(stem)

    if args.json:
        print(json.dumps(
            {"ok": not errors, "stem": str(stem), "errors": errors, "warnings": warnings},
            indent=2,
        ))
        return 1 if errors else 0

    for w in warnings:
        print(f"  ! {w}", file=sys.stderr)
    if errors:
        print("mow close-out gate FAILED:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1

    print(f"mow close-out gate OK: {stem}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

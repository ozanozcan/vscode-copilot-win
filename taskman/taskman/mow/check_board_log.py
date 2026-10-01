"""Fail if the working-tree board log went backwards against a git ref (d#82).

On 2026-09-22 a `git reset --hard` rolled `board/events.jsonl` 2909 -> 2848
lines and `next_ids` task 12303 -> 12282 *together*. The log-derived allocator
passes on that input — the rolled-back log's max task id agrees with the
lowered counter — so 12282 would be reissued. Only the ref knew the higher ids.

Clean means both of:
  - the ref's `board/events.jsonl` bytes are exactly the leading bytes of the
    working tree's (append-only forward motion)
  - every counter in the ref's `board/next_ids` is <= the working tree's

Git stays here, never in `taskman.eventlog` (the store is git-free by contract).

Usage:
  python -m taskman.mow.check_board_log [--against <ref>] [--root <path>]

Exit 0 = clean (or the ref has no board). Exit 1 = regression.
Exit 2 = could not check (not a git repo, unknown ref, no .taskman.toml).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

EVENTS = "board/events.jsonl"
COUNTERS = "board/next_ids"


class CheckError(RuntimeError):
    """The check could not run — never read as clean."""


@dataclass
class Finding:
    file: str
    ref_lines: int
    tree_lines: int
    ref_counters: dict[str, int] = field(default_factory=dict)
    tree_counters: dict[str, int] = field(default_factory=dict)
    message: str = ""


def _run_git(root: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(
            ["git", "-C", str(root), *args], capture_output=True, check=False
        )
    except OSError as exc:
        raise CheckError(f"cannot run git: {exc}") from exc


def _show(root: Path, ref: str, path: str) -> bytes | None:
    # `./` makes git resolve the path relative to `root`, not the toplevel —
    # a .taskman.toml nested below the toplevel would otherwise compare the
    # wrong file (or none at all).
    proc = _run_git(root, "show", f"{ref}:./{path}")
    return proc.stdout if proc.returncode == 0 else None


def _counters(raw: bytes | None) -> dict[str, int]:
    if not raw:
        return {}
    try:
        data = json.loads(raw.decode("utf-8"))
        return {str(k): int(v) for k, v in data.items()}
    except (ValueError, TypeError, AttributeError) as exc:
        # Wrong shape (a list value, null, a top-level array, bad JSON) is
        # "could not check" (exit 2), never a finding (exit 1).
        raise CheckError(f"{COUNTERS} is not a JSON object of ints: {exc}") from exc


def _read(path: Path) -> bytes | None:
    return path.read_bytes() if path.is_file() else None


def recovery(ref: str) -> str:
    return (
        "Recovery, in this order (never the reverse):\n"
        f"  1. rescue appended events first — lines in the working-tree {EVENTS} "
        f"written since the rollback exist nowhere else; copy them out before "
        "anything else.\n"
        f"  2. git checkout {ref} -- {EVENTS} {COUNTERS}\n"
        "  3. re-append the rescued events through `taskman` so they get fresh ids."
    )


def check_board_log(repo_root: Path, *, ref: str = "HEAD") -> Finding | None:
    root = Path(repo_root)
    if _run_git(root, "rev-parse", "--is-inside-work-tree").returncode != 0:
        raise CheckError(f"{root} is not a git work tree")
    if _run_git(root, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}").returncode != 0:
        raise CheckError(f"ref {ref!r} does not resolve to a commit in {root}")

    ref_events = _show(root, ref, EVENTS)
    if ref_events is None:
        print(f"note: {EVENTS} is not committed at {ref} — nothing to check", file=sys.stderr)
        return None
    ref_counters = _counters(_show(root, ref, COUNTERS))

    tree_events = _read(root / EVENTS) or b""
    tree_counters = _counters(_read(root / COUNTERS))

    ref_lines = ref_events.count(b"\n")
    tree_lines = tree_events.count(b"\n")
    problems: list[str] = []
    files: list[str] = []
    if not tree_events.startswith(ref_events):
        files.append(EVENTS)
        problems.append(
            f"{EVENTS}: {ref}'s copy ({ref_lines} lines) is not a byte-prefix of the "
            f"working tree's ({tree_lines} lines)"
        )
    lowered = {
        k: (v, tree_counters.get(k, 0))
        for k, v in sorted(ref_counters.items())
        if v > tree_counters.get(k, 0)
    }
    if lowered:
        files.append(COUNTERS)
        detail = ", ".join(f"{k} {r} > {t}" for k, (r, t) in lowered.items())
        problems.append(f"{COUNTERS}: {ref}'s counter exceeds the working tree's ({detail})")
    if not problems:
        return None
    return Finding(
        file=", ".join(files),
        ref_lines=ref_lines,
        tree_lines=tree_lines,
        ref_counters=ref_counters,
        tree_counters=tree_counters,
        message="; ".join(problems),
    )


def _find_root() -> Path:
    here = Path.cwd().resolve()
    for d in (here, *here.parents):
        if (d / ".taskman.toml").is_file():
            return d
    raise CheckError("no .taskman.toml above cwd — pass --root")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="mow-check-board-log",
        description="Check the working-tree board log against a git ref (d#82).",
    )
    ap.add_argument("--against", default="HEAD", help="git ref to compare with (default HEAD)")
    ap.add_argument("--root", help="repo root (default: walk up for .taskman.toml)")
    args = ap.parse_args(argv)
    try:
        root = Path(args.root).resolve() if args.root else _find_root()
        finding = check_board_log(root, ref=args.against)
    except (CheckError, ValueError) as exc:
        print(f"board-log check could not run: {exc}", file=sys.stderr)
        return 2
    if finding is None:
        print(f"board-log check OK against {args.against}: {root}")
        return 0
    print(f"board-log check FAILED against {args.against}: {finding.message}")
    print(recovery(args.against))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

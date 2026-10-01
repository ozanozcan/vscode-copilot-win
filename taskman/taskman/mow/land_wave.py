#!/usr/bin/env python3
"""Land a merged wave onto the main working tree (mow go §2a step 4).

Diffs the integration branch against its *own* merge-base with the main
checkout's HEAD — never against HEAD itself (L13). A peer commit that reached
main after integration began is absent from the integration branch, so a
HEAD..integrate diff carries its reversal and `git apply` deletes it
(2026-09-26: ffbe7de's 8 files, unnoticed for 2.5h).

Two guards, both keyed on the wave's INDEX ``Files owned``:
  1. before apply — every path in the diff must be owned, else refuse and
     apply nothing;
  2. after apply — every `git status --porcelain` entry the apply changed must
     be owned, else exit 1 naming the paths.

Then it commits exactly the landed paths (``commit_landed``), so the wave never
sits uncommitted where a peer's ai-sync can sweep it (L97, L101).

Usage:
  python -m taskman.mow.land_wave docs/plans/<stem> --wave 2 --integrate mow/<stem>/integrate
  python -m taskman.mow.land_wave docs/plans/<stem> --wave 2 --integrate <branch> --check
"""

from __future__ import annotations

import argparse
import fnmatch
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from taskman.mow.preflight import (
    _resolve_dispatch,
    _split_lanes_table,
    parse_files_owned,
    parse_wave_lanes,
    paths_overlap,
)


def _git(repo: Path, *args: str, stdin: bytes | None = None) -> bytes:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, input=stdin
    ).stdout


def wave_files_owned(stem_dir: Path, wave: str) -> list[str]:
    """Union of INDEX ``Files owned`` for the lanes of one wave."""
    _dispatch, index = _resolve_dispatch(stem_dir)
    text = index.read_text()
    lanes = parse_wave_lanes(text).get(wave)
    if not lanes:
        raise KeyError(f"wave {wave} not found in {index} ## Waves")
    owned: list[str] = []
    for row in _split_lanes_table(text):
        if row["lane"] in lanes:
            owned.extend(parse_files_owned(row["files_owned"]))
    return owned


def changed_paths(repo: Path, a: str, b: str) -> list[str]:
    out = _git(repo, "diff", "--name-only", "--no-renames", "-z", a, b)
    return [p for p in out.decode().split("\0") if p]


def outside_owned(paths: list[str], owned: list[str]) -> list[str]:
    def ok(p: str) -> bool:
        return any(paths_overlap(p, o) or fnmatch.fnmatch(p, o) for o in owned)

    return sorted(p for p in paths if not ok(p))


def porcelain(repo: Path) -> dict[str, str]:
    """path -> XY status, untracked files listed individually."""
    out = _git(repo, "status", "--porcelain", "-z", "--untracked-files=all", "--no-renames")
    entries: dict[str, str] = {}
    for rec in out.decode().split("\0"):
        if rec:
            entries[rec[3:]] = rec[:2]
    return entries


def apply_patch(repo: Path, patch: bytes) -> None:
    _git(repo, "apply", "--check", stdin=patch)
    _git(repo, "apply", stdin=patch)


def commit_landed(repo: Path, paths: list[str], message: str) -> str:
    """Commit exactly ``paths`` as they now stand on disk; return the new sha.

    Built in a private index from the current HEAD, so a peer's staged or dirty
    files never ride along, and the branch moves by compare-and-swap. Paths are
    literal, never globs: ``x[1].py`` must not match a peer's ``x1.py``. Commit
    hooks do not run (``commit-tree``). Uncommitted landed work is what a peer's
    SessionEnd ai-sync swept into a "sync:" commit (L97, L101).
    """
    parent = _git(repo, "rev-parse", "HEAD").decode().strip()
    ref = subprocess.run(
        ["git", "-C", str(repo), "symbolic-ref", "-q", "HEAD"], capture_output=True, text=True
    ).stdout.strip() or "HEAD"
    with tempfile.TemporaryDirectory() as tmp:
        # per command, never exported: a child inheriting it writes the wrong index (L96)
        env = {**os.environ, "GIT_INDEX_FILE": str(Path(tmp) / "index")}

        def private(*args: str, stdin: bytes | None = None) -> bytes:
            return subprocess.run(
                ["git", "--literal-pathspecs", "-C", str(repo), *args],
                check=True, capture_output=True, input=stdin, env=env,
            ).stdout

        private("read-tree", parent)
        private("add", "-A", "--", *paths)
        tree = private("write-tree").decode().strip()
        sha = private("commit-tree", tree, "-p", parent, stdin=message.encode()).decode().strip()
    _git(repo, "update-ref", ref, sha, parent)
    return sha


def sync_shared_index(repo: Path, paths: list[str]) -> None:
    """Point the shared index at HEAD for ``paths`` only. Until this runs, a peer's
    bare ``git commit`` would commit the pre-landing blobs back (a revert)."""
    _git(repo, "--literal-pathspecs", "reset", "-q", "--", *paths)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("stem", type=Path, help="docs/plans/<stem> or …/dispatch")
    p.add_argument("--wave", required=True, help="wave number as written in INDEX ## Waves")
    p.add_argument("--integrate", required=True, help="integration branch holding the merged lanes")
    p.add_argument("--repo", type=Path, default=Path.cwd(), help="main checkout (default: cwd)")
    p.add_argument("--check", action="store_true", help="run the pre-apply guard only")
    args = p.parse_args(argv)
    repo = args.repo.resolve()

    try:
        owned = wave_files_owned(args.stem.resolve(), args.wave)
    except (KeyError, ValueError, OSError) as e:
        print(f"mow land: {e}", file=sys.stderr)
        return 2
    if not owned:
        print(f"mow land: wave {args.wave} owns no files — nothing may land", file=sys.stderr)
        return 2

    # Resolve both ends once, so HEAD moving mid-run cannot widen the diff.
    head = _git(repo, "rev-parse", "HEAD").decode().strip()
    tip = _git(repo, "rev-parse", args.integrate).decode().strip()
    base = _git(repo, "merge-base", head, tip).decode().strip()

    changed = changed_paths(repo, base, tip)
    stray = outside_owned(changed, owned)
    if stray:
        print(
            f"mow land REFUSED: {base[:10]}..{args.integrate} touches paths outside "
            f"wave {args.wave}'s Files owned — nothing applied:",
            file=sys.stderr,
        )
        for s in stray:
            print(f"  - {s}", file=sys.stderr)
        return 1
    # Owned means nobody else is editing it: someone's staged or dirty change on a
    # landed path would be absorbed into the landing commit, so refuse instead.
    before = porcelain(repo)
    busy = sorted(p for p in changed if p in before)
    if busy:
        print(
            f"mow land REFUSED: these landed paths are already modified or staged in "
            f"{repo} — someone else is touching them; nothing applied:",
            file=sys.stderr,
        )
        for b in busy:
            print(f"  - {b} [{before[b]}]", file=sys.stderr)
        return 1
    if not changed:
        print(f"mow land: {args.integrate} has no changes since {base[:10]}")
        return 0
    if args.check:
        print(f"mow land check OK: {len(changed)} path(s), all owned")
        return 0

    patch = _git(repo, "diff", "--binary", "--no-renames", base, tip)
    try:
        apply_patch(repo, patch)
    except subprocess.CalledProcessError as e:
        print(f"mow land: git apply failed — stop and ask:\n{e.stderr.decode()}", file=sys.stderr)
        return 1
    after = porcelain(repo)

    moved = [k for k in before.keys() | after.keys() if before.get(k) != after.get(k)]
    drift = outside_owned(moved, owned)
    if drift:
        print(
            "mow land: applied, but these paths changed outside "
            f"wave {args.wave}'s Files owned — inspect before continuing:",
            file=sys.stderr,
        )
        for d in drift:
            print(f"  - {d}", file=sys.stderr)
        return 1

    stem_name = _resolve_dispatch(args.stem.resolve())[0].parent.name
    message = (
        f"mow {stem_name} wave {args.wave}: land {args.integrate}\n\n"
        f"Landed by taskman.mow.land_wave from {base[:10]}..{args.integrate}; "
        f"{len(changed)} path(s), all in the wave's Files owned.\n"
    )
    try:
        sha = commit_landed(repo, changed, message)
    except subprocess.CalledProcessError as e:
        print(
            "mow land: applied but NOT committed — commit these paths yourself, now:\n"
            f"{e.stderr.decode()}",
            file=sys.stderr,
        )
        for c in changed:
            print(f"  - {c}", file=sys.stderr)
        return 1
    try:
        sync_shared_index(repo, changed)
    except subprocess.CalledProcessError as e:
        print(
            f"mow land: committed {sha[:10]}, but the shared index was NOT synced — run "
            f"`git --literal-pathspecs reset -q -- <paths>` now, or a peer's bare commit "
            f"reverts the landing:\n{e.stderr.decode()}",
            file=sys.stderr,
        )
        for c in changed:
            print(f"  - {c}", file=sys.stderr)
        return 1

    print(f"mow land OK: {len(changed)} path(s) from {base[:10]}..{args.integrate}, committed {sha[:10]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

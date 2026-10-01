#!/usr/bin/env python3
"""Write a worktree-local marker when a VS Code Agent Host session starts."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def git(cwd: Path, *args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(cwd), *args],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def read_payload() -> dict:
    try:
        value = json.load(sys.stdin)
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def safe_session_id(payload: dict, worktree: Path) -> str:
    value = payload.get("session_id") or payload.get("sessionId")
    if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9._-]{1,128}", value):
        return value
    seed = f"{worktree}:{os.getpid()}:{datetime.now(timezone.utc).isoformat()}"
    return "copilot-" + hashlib.sha256(seed.encode()).hexdigest()[:16]


def main() -> int:
    payload = read_payload()
    cwd = Path(str(payload.get("cwd") or os.getcwd())).resolve()
    top = git(cwd, "rev-parse", "--show-toplevel")
    if not top:
        return 0

    worktree = Path(top)
    session_id = safe_session_id(payload, worktree)
    marker_dir = worktree / ".session-markers"
    marker_dir.mkdir(parents=True, exist_ok=True)
    (marker_dir / ".gitignore").write_text("*\n!.gitignore\n", encoding="utf-8")

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    start_sha = git(worktree, "rev-parse", "HEAD") or "UNKNOWN"
    marker = marker_dir / f"{session_id}.json"
    marker.write_text(json.dumps({
        "schema": 1,
        "session_id": session_id,
        "started_at": now,
        "updated_at": now,
        "start_sha": start_sha,
        "branch": git(worktree, "branch", "--show-current") or "",
        "worktree": str(worktree),
        "runtime": "copilot",
        "source": payload.get("source"),
    }, indent=2) + "\n", encoding="utf-8")

    relative_marker = marker.relative_to(worktree).as_posix()
    context = f"Session marker written at {relative_marker} (start_sha={start_sha[:12]})."
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": context,
        }
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
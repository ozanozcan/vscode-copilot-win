#!/usr/bin/env python3
"""End-to-end acceptance for the exported wrap-up path on Windows and POSIX."""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]


def run_python(*args, cwd=None, input_text=None):
    if os.name == "nt":
        launcher = f'"{REPO / "bin/py.cmd"}"'
        command = f'"{launcher} {subprocess.list2cmdline([*map(str, args)])}"'
        invocation = ["cmd.exe", "/d", "/s", "/c", command]
    else:
        invocation = ["sh", str(REPO / "bin/py"), *map(str, args)]
    return subprocess.run(
        invocation,
        cwd=cwd,
        input=input_text,
        capture_output=True,
        text=True,
        timeout=20,
    )


def git(worktree, *args):
    return subprocess.run(
        ["git", "-C", str(worktree), *args],
        check=True,
        capture_output=True,
        text=True,
    )


def main():
    with tempfile.TemporaryDirectory() as directory:
        worktree = Path(directory) / "wrapup acceptance repo"
        worktree.mkdir()
        git(worktree, "init")
        git(worktree, "config", "user.email", "test@example.invalid")
        git(worktree, "config", "user.name", "Acceptance Test")
        (worktree / "README.md").write_text("acceptance\n", encoding="utf-8")
        git(worktree, "add", "README.md")
        git(worktree, "commit", "-m", "initial")

        session_id = "windows-acceptance"
        hook = run_python(
            REPO / ".github/hooks/session-start.py",
            cwd=worktree,
            input_text=json.dumps({
                "hook_event_name": "SessionStart",
                "session_id": session_id,
                "cwd": str(worktree),
                "source": "startup",
            }),
        )
        marker = worktree / ".session-markers" / f"{session_id}.json"
        if hook.returncode != 0 or not marker.is_file():
            print(f"FAIL: SessionStart marker: {hook.stderr}")
            return 1

        board = worktree / "board"
        board.mkdir()
        event = {
            "v": 1,
            "type": "task.add",
            "id": 7,
            "session": session_id,
            "fields": {"title": "Windows wrap-up acceptance", "status": "done"},
        }
        (board / "events.jsonl").write_text(json.dumps(event) + "\n", encoding="utf-8")
        digest = run_python(
            REPO / ".github/skills/wrap-up/scripts/session_digest.py",
            "--session-id", session_id,
            "--board-dir", board,
            cwd=worktree,
        )
        if digest.returncode != 0 or "#7 Windows wrap-up acceptance - done" not in digest.stdout:
            print(f"FAIL: wrap-up digest: {digest.stdout}{digest.stderr}")
            return 1

    print(f"PASS: wrap-up acceptance on {sys.platform}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
#!/usr/bin/env python3
"""Keep MOW tracker timestamps current after VS Code Copilot file edits."""

from __future__ import annotations

import datetime
import json
import os
import sys
import tempfile
from pathlib import Path

MAX_TRACKER_BYTES = 5 * 1024 * 1024


def tool_input(payload: dict) -> dict:
    value = payload.get("toolArgs", payload.get("tool_input", {}))
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return {}
    return value if isinstance(value, dict) else {}


def tracker_path(payload: dict) -> Path | None:
    values = tool_input(payload)
    raw_path = (
        values.get("file_path")
        or values.get("filePath")
        or values.get("path")
        or payload.get("file_path")
    )
    if not isinstance(raw_path, str) or not raw_path:
        return None
    root = Path(payload.get("cwd") or os.getcwd()).resolve()
    path = Path(raw_path)
    if not path.is_absolute():
        path = root / path
    try:
        path = path.resolve()
        path.relative_to(root)
    except (OSError, ValueError):
        return None
    if path.name != "tracker.json" or "dispatch" not in path.parts:
        return None
    return path


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return 0
    if not isinstance(payload, dict):
        return 0

    path = tracker_path(payload)
    if path is None:
        return 0
    try:
        if path.stat().st_size > MAX_TRACKER_BYTES:
            return 0
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return 0
    if not isinstance(data, dict) or "waves" not in data:
        return 0

    data["updated"] = (
        datetime.datetime.now(datetime.timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            delete=False,
        ) as stream:
            temporary_path = Path(stream.name)
            json.dump(data, stream, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary_path, path.stat().st_mode)
        os.replace(temporary_path, path)
    except OSError:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
#!/usr/bin/env python3
"""Direct release check used when optional Agent Host hooks are unavailable."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def git_checkout(root: Path) -> bool:
    result = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--is-inside-work-tree"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0 and result.stdout.strip() == "true"


def run_check(root: Path, label: str, command: list[str]) -> bool:
    result = subprocess.run(
        command,
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        print(f"release fallback passed: {label}")
        return True
    print(f"release fallback BLOCKED: {label} failed", file=sys.stderr)
    if result.stdout:
        print(result.stdout, end="", file=sys.stderr)
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)
    return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--hooks-disabled", action="store_true")
    args = parser.parse_args(argv)
    root = args.root.resolve()

    if not git_checkout(root):
        print(f"release fallback BLOCKED: {root} is not a Git checkout", file=sys.stderr)
        return 2

    checks = [
        ("Git whitespace", ["git", "diff", "--check", "HEAD"]),
        ("Harness checks", [sys.executable, "bin/tests/test_repo_shape.py"]),
        ("Workspace customization checks",
         [sys.executable, "bin/tests/test_public_customizations.py"]),
    ]
    for label, command in checks:
        if not run_check(root, label, command):
            return 1

    mode = "hooks disabled" if args.hooks_disabled else "hooks optional"
    print(f"release fallback OK ({mode}): git diff --check HEAD")
    return 0


if __name__ == "__main__":
    sys.exit(main())
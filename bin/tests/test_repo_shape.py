#!/usr/bin/env python3
"""Contract checks for the exported public repository shape."""

import re
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
FAILURES = []


def check(label, got, want=True):
    if got == want:
        print(f"  PASS  {label}")
    else:
        print(f"  FAIL  {label} - got {got!r}, want {want!r}")
        FAILURES.append(label)


def main():
    print("public repository shape")

    required = [
        ".github/copilot-instructions.md",
        ".github/agents/mow-implementer.agent.md",
        ".github/agents/mow-reviewer.agent.md",
        ".github/skills/mow/SKILL.md",
        ".github/skills/taskman/SKILL.md",
        ".github/skills/impeccable/LICENSE",
        "bin/bootstrap-taskman.py",
        "bin/py",
        "bin/py.cmd",
        "docs/onboarding/work-pc.agent.md",
        "docs/onboarding/work-pc.human.md",
        "skills.lock.json",
        "taskman/pyproject.toml",
    ]
    check("required release assets exist",
          [path for path in required if not (REPO / path).is_file()], [])

    skills = REPO / ".github" / "skills"
    skill_dirs = sorted(path for path in skills.iterdir() if path.is_dir()) \
        if skills.is_dir() else []
    check("every bundled skill has a SKILL.md",
          [path.name for path in skill_dirs if not (path / "SKILL.md").is_file()], [])

    forbidden = [".taskman.toml", "board", "local.config.json", "CLAUDE.md", "global"]
    check("private repository state is absent",
          [path for path in forbidden if (REPO / path).exists()], [])

    leak = re.compile(r"/Users/[A-Za-z0-9._-]+|\\Users\\[A-Za-z0-9._-]+", re.I)
    leaked = []
    for root in (REPO / ".github", REPO / "bin", REPO / "docs", REPO / "taskman"):
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if not path.is_file() or "__pycache__" in path.parts:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            if leak.search(text):
                leaked.append(path.relative_to(REPO).as_posix())
    check("public files contain no absolute user paths", leaked, [])

    print()
    if FAILURES:
        print(f"{len(FAILURES)} failure(s): " + ", ".join(FAILURES))
        return 1
    print("0 failure(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
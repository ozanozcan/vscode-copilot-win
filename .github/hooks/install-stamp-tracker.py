#!/usr/bin/env python3
"""Install the optional MOW tracker hook outside the active workspace."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--copilot-home",
        type=Path,
        default=Path(os.environ.get("COPILOT_HOME") or Path.home() / ".copilot"),
    )
    args = parser.parse_args(argv)

    source = Path(__file__).resolve().with_name("stamp-tracker.py")
    script = args.copilot_home.resolve() / "ai-wow-hooks" / "stamp-tracker.py"
    registration = args.copilot_home.resolve() / "hooks" / "ai-wow-stamp-tracker.json"
    script.parent.mkdir(parents=True, exist_ok=True)
    registration.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, script)

    powershell_path = str(script).replace("'", "''")
    config = {
        "version": 1,
        "hooks": {
            "postToolUse": [{
                "type": "command",
                "matcher": "edit|create",
                "bash": f"python3 {shlex.quote(script.as_posix())}",
                "powershell": f"py -3 '{powershell_path}'",
                "timeoutSec": 5,
            }],
        },
    }
    registration.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    print(f"installed tracker hook: {registration}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
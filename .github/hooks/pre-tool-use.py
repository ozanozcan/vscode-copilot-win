#!/usr/bin/env python3
"""Optional VS Code Copilot Agent Host hook capability probe.

This program deliberately makes no authorization decision. A managed-host probe
must establish the actual Copilot SDK event and response contracts before a hook
can inspect payload fields. The standalone release guard is the enforcement path.
"""

from __future__ import annotations

import json
import os
import sys


CAPABILITY_ENV = "COPILOT_AGENT_HOST_HOOKS"


def payload_is_json_object(raw: str) -> bool:
    """Check whether stdin is structured without trusting any field in it."""
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return False
    return isinstance(payload, dict)


def main() -> int:
    raw = sys.stdin.read()
    if os.environ.get(CAPABILITY_ENV) != "1":
        print(
            "Agent Host hook capability is not enabled; run the release fallback directly.",
            file=sys.stderr,
        )
        return 0

    payload_kind = "a JSON object" if payload_is_json_object(raw) else "an unrecognized payload"
    print(
        f"Agent Host hook capability probe received {payload_kind}; "
        "no payload contract is verified, so no decision was made. "
        "Run the release fallback directly.",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())